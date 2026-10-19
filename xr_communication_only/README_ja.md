# Quest 3用 VR通信ライブラリ抽出版

Ubuntuでのconda環境構築・USBカメラ配信・Quest接続の手順は、プロジェクト直下の [README.md](../README.md) を参照してください。

元コード: /Users/shunkiyao/program/g1_develpment/xr_teleoperate-main/teleop

## 抽出したもの
- televuer: Quest 3ブラウザーとのHTTPS/WebSocket通信、頭・手・コントローラー入力、VRへの映像表示。
- teleimager: 任意のカメラのZMQ/WebRTC映像配信。映像不要ならインストール不要。
- examples/vr_receive_only.py: ロボットを操作せず、元のVRデータをJSONで表示するサンプル。

G1などのrobot_control、Unitree SDK/DDS、逆運動学、URDF、歩行制御、録画処理は含みません。
TeleVuerWrapper/TeleDataはUnitree固有の変換を避けるため除外し、televuerの公開APIをTeleVuerだけに変更しました。
上流のREADMEとLICENSEは帰属・参考情報のため保持しています。READMEのUnitree制御手順は今回の実行手順ではありません。

## インストール
このディレクトリで実行します。両ライブラリを使う場合の共通Pythonバージョン範囲は3.10〜3.11です。

```bash
python -m pip install -e ./televuer
# 映像クライアントが必要な場合
python -m pip install -e ./teleimager
# カメラ配信サーバーも必要な場合（UVC依存は環境により追加セットアップが必要）
python -m pip install -e './teleimager[server]'
```

## Quest 3から受信
既存の証明書を指定します。

```bash
python examples/vr_receive_only.py --cert /absolute/path/cert.pem --key /absolute/path/key.pem
```

Quest 3をPCへ通信可能なネットワークに接続し、ブラウザーで以下を開いてXRモードへ入ります。

`https://<PCのIP>:8012/?ws=wss://<PCのIP>:8012`

既定はコントローラー入力です。ハンド入力には `--hands` を追加します。
TLS証明書をQuest側で受け入れる必要があります。証明書設定の詳細は上流televuer/README.md参照。

## 既存ROS 2 bridgeとの接続

```python
from televuer import TeleVuer
# TeleVuerの初期化はexamples/vr_receive_only.pyを参照
# xr.head_pose / xr.left_arm_pose / xr.right_arm_pose: 4x4行列
# xr.left_ctrl_thumbstickValue / xr.right_ctrl_thumbstickValue: 2要素
# xr.right_ctrl_bButton / xr.left_ctrl_bButton: B/Yボタン
```

姿勢はXRのワールド基準で、座標軸はX右・Y上・Z後方です。手とコントローラーでは姿勢の意味が異なるため、対象ロボットの基準・工具姿勢への変換はbridge側で定義してください。
元フォルダーのxr_button_bridge_node.pyはROS 2側でUDPのバイナリ入力を受ける実装です。この受信サンプルのJSON出力をそのまま渡すことはできません。bridge構築済みという前提で、bridge自体は複製・変更していません。既存の送信処理をTeleVuerのプロパティに接続してください。

motion_data_readyは初回受信後にTrueになるだけで、現在の接続状態を示しません。sample_time_unixも読み取り時刻です。ロボットを動かす際には受信イベントの時刻によるタイムアウトが必要です。各プロパティの取得は個別で、全項目が同一フレームになる保証はありません。

## 映像配信
teleimager/cam_config_server.yamlは上流のカメラ設定例です。G1用のカメラ識別子・左右手首カメラ設定が残るので、使うカメラに合わせて変更してください。
通常のカメラ配信はUnitree SDK不要です。上流teleimagerの任意機能IsaacSimCameraのみ外部のtools.shared_memory_utilsに依存し、この抽出にはその外部ツールを含めていません。Isaac Simモードを使わなければ不要です。
Unitree表記・ロゴは元のライブラリの表示資産で、ロボット制御への依存ではありません。

## 変更と確認
元リポジトリは変更していません。ソースファイルの抽出元と元ファイルのSHA-256はEXTRACTION_MANIFEST.jsonに記録しています。抽出後の変更はtelevuer/__init__.pyの公開APIとパッケージ説明だけです。
Python構文と内部相対importの存在を確認しました。Quest 3接続、実カメラ、既存ROS 2 bridgeとの実行確認は未実施です。
