"""Receive raw XR tracking data without Unitree robot control.
Install the local teleop/televuer package before running.
"""
import argparse
import json
import time
from televuer import TeleVuer


def snapshot(xr, hands):
    data = {
        "sample_time_unix": time.time(),
        "coordinate_basis": "OpenXR: x right, y up, z back",
        "motion_data_ready": xr.motion_data_ready,
        "head_pose": xr.head_pose.tolist(),
        "left_pose": xr.left_arm_pose.tolist(),
        "right_pose": xr.right_arm_pose.tolist(),
    }
    for side in ("left", "right"):
        if hands:
            fields = ("hand_positions", "hand_orientations", "hand_pinch",
                      "hand_pinchValue", "hand_squeeze", "hand_squeezeValue")
        else:
            fields = ("ctrl_trigger", "ctrl_triggerValue", "ctrl_squeeze",
                      "ctrl_squeezeValue", "ctrl_thumbstick", "ctrl_thumbstickValue",
                      "ctrl_aButton", "ctrl_bButton")
        for field in fields:
            value = getattr(xr, f"{side}_{field}")
            data[f"{side}_{field}"] = value.tolist() if hasattr(value, "tolist") else value
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hands", action="store_true", help="Use hands instead of controllers")
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--hz", type=float, default=10.0)
    parser.add_argument("--webrtc-url", help="Camera offer URL reachable from the headset, e.g. https://192.168.0.20:60001/offer")
    parser.add_argument("--binocular", action="store_true", help="Camera provides side-by-side stereo images")
    args = parser.parse_args()
    if args.hz <= 0:
        parser.error("--hz must be positive")
    xr = TeleVuer(
        use_hand_tracking=args.hands,
        binocular=args.binocular,
        img_shape=(480, 640),
        display_mode="ego" if args.webrtc_url else "pass-through",
        zmq=False,
        webrtc=bool(args.webrtc_url),
        webrtc_url=args.webrtc_url,
        cert_file=args.cert,
        key_file=args.key,
    )
    try:
        while True:
            # Individual fields are read separately, not an atomic tracking frame.
            # sample_time_unix is the polling time, not the last XR event time.
            print(json.dumps(snapshot(xr, args.hands), allow_nan=False), flush=True)
            time.sleep(1.0 / args.hz)
    except KeyboardInterrupt:
        pass
    finally:
        xr.close()


if __name__ == "__main__":
    main()
