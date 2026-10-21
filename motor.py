"""3輪オムニ車体を Quest 3 (TeleVuer) で操作する版。
モータ・カメラサーボへの出力処理は motor.py と同一で、入力だけを VR に置き換えている。

操作:
  右A        : ロック解除（同時に頭の正面向きを基準に再設定）
  右B        : ロック
  右トリガー : 頭の正面向きを再設定（今向いている方向を正面にする）
  左スティック: 3輪オムニ全方位移動（並進）
  頭の左右振り向き: 旋回（基準からのヨー角に比例した旋回速度）
  右スティック上下: 後ろ2輪によるまっすぐ前進・後退（motor.py の右スティック機能）
  左Y / 左X  : カメラ上 / 下

実行例:
  python motor_vr.py --cert certs/cert.pem --key certs/key.pem
  python motor_vr.py --cert certs/cert.pem --key certs/key.pem --webrtc-url https://<IP>:60001/offer
"""
import argparse
import time
import math

import numpy as np
import RPi.GPIO as GPIO
from televuer import TeleVuer

# ==========================================
# 🎛️ 【調整用パラメータ】
# ==========================================
MOVE_SPEED_SCALE = 1.0
TURN_SPEED_SCALE = 1.0
LEFT_TURN_BOOST  = 1.4
MAX_SERVO_RANGE  = 1.0
DEADZONE         = 0.40  # スティック全体の傾きに対するデッドゾーン

# 各オムニサーボの完全停止位置（トリム調整）
TRIM_1 = 7.5  # サーボ1 (左下 / バツ)
TRIM_2 = 7.5  # サーボ2 (右下 / 四角)
TRIM_3 = 7.5  # サーボ3 (上・前 / 三角)

# ★前輪（サーボ3）の個別スピード調整係数
SERVO3_SCALE = 0.7

# 左右移動時のパワー補正倍率
MOVE_BOOST = 1.6

# --- カメラ用サーボの設定 (ピン22) ---
SERVO_CAM = 22
CAM_NEUTRAL = 7.5     # カメラの初期中央位置
cam_duty = CAM_NEUTRAL
CAM_MIN = 5.0         # 下向きの限界
CAM_MAX = 10.0        # 上向きの限界
CAM_STEP = 0.025      # カメラボタン1回あたりの変化量

# --- VR 入力用パラメータ ---
HEAD_YAW_DEADZONE_DEG = 15.0  # この角度以内の首振りでは旋回しない
HEAD_YAW_MAX_DEG      = 45.0  # この角度で旋回速度が最大になる
HEAD_TILT_LIMIT       = 0.3   # 真下/真上を向いて前方向ベクトルの水平成分がこれ未満なら旋回入力を無視
TRIGGER_THRESHOLD     = 0.5   # 右トリガー（正面再設定）の押下判定
INPUT_TIMEOUT_S       = 0.5   # 頭・コントローラー姿勢がこの時間更新されなければ通信断とみなして停止・ロック
LOOP_DT               = 0.02
# ==========================================

# --- ピン設定 ---
SERVO_OMNI_1 = 17  # バツ
SERVO_OMNI_2 = 18  # 四角
SERVO_OMNI_3 = 27  # 三角 (正面側)


def head_yaw_left(head_pose):
    """頭の左回りヨー角[rad]（OpenXR: x右, y上, z後方）。水平に近い視線が取れなければ None。"""
    r = head_pose[:3, :3]
    fx, fz = -r[0, 2], -r[2, 2]  # 視線方向 = -Z 軸の水平成分
    if math.hypot(fx, fz) < HEAD_TILT_LIMIT:
        return None
    return math.atan2(-fx, -fz)


def wrap_pi(a):
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def main():
    global cam_duty

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--webrtc-url", help="Quest に映像を出す場合のカメラ offer URL (例: https://192.168.0.20:60001/offer)")
    parser.add_argument("--binocular", action="store_true", help="カメラが左右横並びステレオ映像の場合")
    args = parser.parse_args()

    GPIO.setmode(GPIO.BCM)
    pins = [SERVO_OMNI_1, SERVO_OMNI_2, SERVO_OMNI_3, SERVO_CAM]
    for pin in pins:
        GPIO.setup(pin, GPIO.OUT)

    pwm1 = GPIO.PWM(SERVO_OMNI_1, 50)
    pwm2 = GPIO.PWM(SERVO_OMNI_2, 50)
    pwm3 = GPIO.PWM(SERVO_OMNI_3, 50)
    pwm_cam = GPIO.PWM(SERVO_CAM, 50)

    pwm1.start(0); pwm2.start(0); pwm3.start(0); pwm_cam.start(0)

    xr = None
    try:
        xr = TeleVuer(
            use_hand_tracking=False,
            binocular=args.binocular,
            img_shape=(480, 640),
            display_mode="ego" if args.webrtc_url else "pass-through",
            zmq=False,
            webrtc=bool(args.webrtc_url),
            webrtc_url=args.webrtc_url,
            cert_file=args.cert,
            key_file=args.key,
        )

        is_locked = True
        yaw_ref = None          # 頭の正面基準ヨー角
        last_poses = None       # 通信断検出用
        last_update = 0.0
        stale_reported = False

        print("\n【VRコントローラー版オムニ制御起動】")
        print("・右A: ロック解除(+正面再設定) / 右B: ロック / 右トリガー: 正面再設定")
        print("・左スティック: 全方位移動 / 頭の左右振り向き: 旋回")
        print("・右スティック上/下: 後ろ2輪でまっすぐ前進・後退")
        print("・左Y / 左X: カメラ上 / 下")
        print("Quest のブラウザーで https://<このPCのIP>:8012/?ws=wss://<このPCのIP>:8012 を開いてください")
        print("---------------------------------------------------")

        def stop_wheels():
            pwm1.ChangeDutyCycle(0)
            pwm2.ChangeDutyCycle(0)
            pwm3.ChangeDutyCycle(0)

        while True:
            now = time.monotonic()

            # --- 通信断の検出（姿勢が一定時間まったく変化しなければ停止） ---
            head_pose = xr.head_pose
            poses = np.concatenate([head_pose.ravel(), xr.left_arm_pose.ravel(), xr.right_arm_pose.ravel()])
            if last_poses is None or not np.array_equal(poses, last_poses):
                last_poses = poses
                last_update = now
            alive = xr.motion_data_ready and (now - last_update) < INPUT_TIMEOUT_S

            if not alive:
                if not is_locked or not stale_reported:
                    print(">>> VR入力なし：停止・ロック        ", end="\r")
                    stale_reported = True
                is_locked = True
                stop_wheels()
                pwm_cam.ChangeDutyCycle(0)
                time.sleep(LOOP_DT)
                continue
            stale_reported = False

            # --- ロック・解除 ---
            yaw = head_yaw_left(head_pose)
            if xr.right_ctrl_aButton:  # 右A (○相当)
                if is_locked:
                    print(">>> ロック解除：走行可能", end="\r")
                is_locked = False
                if yaw is not None:
                    yaw_ref = yaw
            if xr.right_ctrl_bButton:  # 右B (×相当)
                if not is_locked:
                    print(">>> ロック中：停止状態  ", end="\r")
                is_locked = True

            # --- 頭の正面再設定 ---
            if xr.right_ctrl_triggerValue > TRIGGER_THRESHOLD and yaw is not None:
                yaw_ref = yaw

            # --- カメラの上下操作 ---
            cam_moved = False
            if xr.left_ctrl_bButton:    # 左Y (△相当)
                cam_duty += CAM_STEP
                if cam_duty > CAM_MAX: cam_duty = CAM_MAX
                cam_moved = True
            elif xr.left_ctrl_aButton:  # 左X (□相当)
                cam_duty -= CAM_STEP
                if cam_duty < CAM_MIN: cam_duty = CAM_MIN
                cam_moved = True

            if cam_moved:
                pwm_cam.ChangeDutyCycle(cam_duty)
            else:
                pwm_cam.ChangeDutyCycle(0)

            if is_locked:
                stop_wheels()
                time.sleep(LOOP_DT)
                continue

            # ==========================================
            # 🎮 移動入力の取得
            # ==========================================
            left_stick = xr.left_ctrl_thumbstickValue    # [x(右+), y(前-)]
            right_stick = xr.right_ctrl_thumbstickValue

            # 1. 右スティックの縦軸（上がマイナス、下がプラス：motor.py と同じ向き）
            right_stick_y = float(right_stick[1])

            # 頭のヨー角による旋回（左向き → turn マイナス、右向き → プラス：motor.py の L2/R2 と同じ符号）
            turn = 0.0
            if yaw is not None and yaw_ref is not None:
                dyaw = math.degrees(wrap_pi(yaw - yaw_ref))  # 左向きが正
                if abs(dyaw) > HEAD_YAW_DEADZONE_DEG:
                    power = (abs(dyaw) - HEAD_YAW_DEADZONE_DEG) / (HEAD_YAW_MAX_DEG - HEAD_YAW_DEADZONE_DEG)
                    power = min(power, 1.0)
                    if dyaw > 0:
                        turn = - power * TURN_SPEED_SCALE * LEFT_TURN_BOOST
                    else:
                        turn = power * TURN_SPEED_SCALE

            # ===== ここから下のモータ出力は motor.py と同一 =====

            # --- ① 右スティックが上下に大きく倒されている場合（綺麗に前進・後退） ---
            if abs(right_stick_y) > DEADZONE:
                s1, s2, s3 = 0.0, 0.0, 0.0

                power = (abs(right_stick_y) - DEADZONE) / (1.0 - DEADZONE)
                power = min(max(power, 0.0), 1.0) * MOVE_SPEED_SCALE

                if right_stick_y < 0:  # 上方向へ倒す【前進】
                    s1 =  0.8 * power
                    s2 = -0.8 * power
                    s3 =  0.0
                else:                  # 下方向へ倒す【後退】
                    s1 = -0.8 * power
                    s2 =  0.8 * power
                    s3 =  0.0

                s1 += turn; s2 += turn; s3 += turn

                pwm1.ChangeDutyCycle(TRIM_1 + s1 * MAX_SERVO_RANGE)
                pwm2.ChangeDutyCycle(TRIM_2 + s2 * MAX_SERVO_RANGE)
                pwm3.ChangeDutyCycle(TRIM_3 + (s3 * MAX_SERVO_RANGE * SERVO3_SCALE))

            else:
                # --- ② 左スティックのベクトル操作（全方位移動） ---
                raw_x = float(left_stick[0])
                raw_y = -float(left_stick[1])

                raw_vx = raw_y
                raw_vy = raw_x

                magnitude = math.hypot(raw_vx, raw_vy)

                vx = 0.0
                vy = 0.0

                if magnitude >= DEADZONE:
                    scaled_mag = (magnitude - DEADZONE) / (1.0 - DEADZONE)
                    scaled_mag = min(scaled_mag, 1.0)

                    vx = (raw_vx / magnitude) * scaled_mag * MOVE_SPEED_SCALE
                    vy = (raw_vy / magnitude) * scaled_mag * MOVE_SPEED_SCALE

                if vx == 0.0 and vy == 0.0 and turn == 0.0:
                    stop_wheels()
                else:
                    theta1 = math.radians(240)  # サーボ1 (左下)
                    theta2 = math.radians(120)  # サーボ2 (右下)
                    theta3 = math.radians(0)    # サーボ3 (上・前)

                    s1 = -vx * math.sin(theta1) + vy * math.cos(theta1) + turn
                    s2 = -vx * math.sin(theta2) + vy * math.cos(theta2) + turn
                    s3 = -vx * math.sin(theta3) + vy * math.cos(theta3) + turn

                    if abs(vy) > 0.2 or abs(vx) > 0.2:
                        s1 *= MOVE_BOOST
                        s2 *= MOVE_BOOST
                        s3 *= MOVE_BOOST

                    target_duty1 = TRIM_1 + s1 * MAX_SERVO_RANGE
                    target_duty2 = TRIM_2 + s2 * MAX_SERVO_RANGE
                    target_duty3 = TRIM_3 + (s3 * MAX_SERVO_RANGE * SERVO3_SCALE)

                    pwm1.ChangeDutyCycle(target_duty1)
                    pwm2.ChangeDutyCycle(target_duty2)
                    pwm3.ChangeDutyCycle(target_duty3)

            time.sleep(LOOP_DT)

    except KeyboardInterrupt:
        print("\n終了します...")

    finally:
        for p in [pwm1, pwm2, pwm3, pwm_cam]:
            p.stop()
        GPIO.cleanup()
        if xr is not None:
            xr.close()
        print("安全に終了しました。")


if __name__ == "__main__":
    main()
