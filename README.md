# bool_robot：Ubuntu導入手順

Quest 3の姿勢・コントローラー／ハンド入力を受信し、必要に応じてUSBカメラ映像をQuestに表示する環境です。ロボット制御、ROS 2、Unitree SDKは含みません。

Ubuntuがインストール済みのPCを対象にします。USBカメラはUbuntuのPCへ接続し、QuestはそのPCと通信できる同一LANへ接続してください。WSLや仮想マシンではUSB転送・ネットワークの追加設定が必要になるため、この手順では扱いません。

## 1. プロジェクトを配置する

このフォルダー全体をUbuntuの `~/bool_robot` へコピーします。別の場所に配置した場合は以降の `cd` を読み替えてください。Windowsのconda環境そのものはコピーせず、Ubuntuで作成し直します。

```text
bool_robot/
├── README.md
├── vr_receive_only.py
└── xr_communication_only/
    ├── televuer/
    └── teleimager/
```

## 2. condaを用意する

既に `conda --version` が動く場合は、この節をスキップします。
未導入の場合は、conda-forgeを標準で使うMiniforgeをインストールします。

```bash
sudo apt update
sudo apt install -y curl ca-certificates
mkdir -p ~/Downloads
cd ~/Downloads
curl -fL -O "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-$(uname -m).sh"
bash "Miniforge3-Linux-$(uname -m).sh"
```

画面の案内に従ってインストールし、シェルの初期化を有効にします。ターミナルを開き直して確認してください。初期化しなかった場合は、標準のインストール先なら `source ~/miniforge3/etc/profile.d/conda.sh` で現在のターミナルに読み込めます。

```bash
conda --version
```

## 3. Python環境とVRライブラリをインストールする

両ライブラリの共通Python対応範囲は3.10～3.11です。この手順は3.10を使用します。

```bash
cd ~/bool_robot
conda create -n bool_robot --override-channels -c conda-forge python=3.10 pip openssl -y
source ~/miniconda3/etc/profile.d/conda.sh
conda activate bool_robot
python -m pip install -e ./xr_communication_only/televuer
python -m pip check
python -m pip install "params-proto==2.13.2"
python -c "from televuer import TeleVuer; print('import OK')"
```

`import OK` が表示されれば読み込みは成功です。`vuer==0.0.60` に合わせて `params-proto==2.13.2` を依存設定で固定しています。

既に `bool_robot` 環境がある場合は、環境作成を省略して `conda activate bool_robot` から実行してください。

## 4. UbuntuのIPと証明書を用意する

```bash
hostname -I
```

複数のIPが出る場合は、Questと同じLANのWi-Fi／EthernetのIPv4アドレスを使います。以降の `192.168.0.20` は例なので実際のIPに置き換えてください。

```bash
cd ~/bool_robot
source ~/miniconda3/etc/profile.d/conda.sh
conda activate bool_robot
mkdir -p certs
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout certs/key.pem \
  -out certs/cert.pem \
  -subj "/CN=192.168.0.20" \
  -addext "subjectAltName=IP:192.168.0.20,IP:127.0.0.1,DNS:localhost"
chmod 600 certs/key.pem
openssl x509 -in certs/cert.pem -noout -subject -dates -ext subjectAltName
```

上の生成コマンドは同名ファイルを上書きするため、証明書が既にある場合は再利用するか退避してください。IPが変わった場合は新しいIPで作り直します。`key.pem` は秘密鍵なので共有・公開しないでください。

## 5. まずVR入力だけで接続を確認する

```bash
cd ~/bool_robot
source ~/miniconda3/etc/profile.d/conda.sh
conda activate bool_robot
python vr_receive_only.py --cert certs/cert.pem --key certs/key.pem
```

Questのブラウザーで次を開き、自己署名証明書の警告を確認して接続を許可し、XRモードに入ります。

```text
https://192.168.0.20:8012/?ws=wss://192.168.0.20:8012
```

ターミナルにJSONが繰り返し出力されます。接続前は `motion_data_ready` が `0`、姿勢がゼロでも正常です。初回受信後に `motion_data_ready` が `1` になり、姿勢やボタン値が変わるか確認します。これは継続的な接続状態の指標ではありません。

ハンド入力を使う場合は `--hands` を追加します。終了は `Ctrl+C` です。

## 6. USBカメラ配信をインストールする（映像が必要な場合）

一般的なUSBカメラ1台をOpenCV経由で640×480、30fpsで使用する設定例です。カメラがこの解像度・fpsに対応しているか後で確認してください。

```bash
sudo apt update
sudo apt install -y build-essential pkg-config libusb-1.0-0-dev libturbojpeg-dev libgl1 v4l-utils
cd ~/bool_robot
source ~/miniconda3/etc/profile.d/conda.sh
conda activate bool_robot
python -m pip install -e "./xr_communication_only/teleimager[server]"
python -m pip check
python -c "import uvc; import teleimager.image_server; print('camera imports OK')"
```

この抽出版はOpenCVカメラでも機器探索に `uvc` を使用するため、`[server]` のインストールが必要です。上流の最新版は構成が異なるので、このフォルダーのローカルパッケージを使用してください。

カメラのアクセス権を設定します。

```bash
sudo usermod -aG video "$USER"
```

一度ログアウトしてログインし直します。カメラを接続し、ほかのカメラアプリを終了してから確認します。

```bash
v4l2-ctl --list-devices
v4l2-ctl -d /dev/video0 --list-formats-ext
```

### カメラ設定を適用する

元の設定は複数のロボット用カメラを前提としているため、1台用の設定へ切り替えます。

```bash
cd ~/bool_robot
cp -n xr_communication_only/teleimager/cam_config_server.yaml xr_communication_only/teleimager/cam_config_server.yaml.bak
cp xr_communication_only/teleimager/cam_config_usb_example.yaml xr_communication_only/teleimager/cam_config_server.yaml
```

必要なら `xr_communication_only/teleimager/cam_config_server.yaml` を編集します。

| 項目 | 初期値 | 設定内容 |
| --- | --- | --- |
| `type` | `opencv` | 通常のUSBカメラをOpenCVで取得 |
| `video_id` | `"0"` | `/dev/video0` の番号。別番号なら変更 |
| `image_shape` | `[480, 640]` | `[高さ, 幅]` |
| `fps` | `30` | カメラの対応fps |
| `binocular` | `false` | 通常の単眼カメラ |
| `webrtc_port` | `60001` | Quest向けWebRTCのHTTPSポート |
| `zmq_port` | `55555` | PC向け映像確認用 |

現在の実装では数値の `0` が未指定扱いになるため、`video_id: "0"` の引用符を残してください。`serial_number` と `physical_path` は `null` のままにします。これらを指定すると `video_id` より優先されます。左右手首カメラは無効化済みです。

## 起動コマンド
### ターミナルA：カメラ配信

```bash
cd ~/bool_robot
source ~/miniconda3/etc/profile.d/conda.sh
conda activate bool_robot
export XR_TELEOP_CERT="$PWD/certs/cert.pem"
export XR_TELEOP_KEY="$PWD/certs/key.pem"
teleimager-server --no-affinity
```

この版は起動時に `sudo modprobe` でUVCドライバーの再読み込みを試みます。パスワードを求められたら入力してください。ほかのUSBカメラにも影響するので、カメラ使用中のアプリを先に終了します。サーバー全体を `sudo` で起動する必要はありません。

`--no-affinity` はCPUコア番号の固定を無効化します。カメラの詳細な探索だけを行う場合は `teleimager-server --cf --no-affinity` も利用できます。

### ターミナルB：Quest向けVR画面を起動

入力だけの受信プログラムが動いている場合は先に `Ctrl+C` で終了します。

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate bool_robot
cd ~/bool_robot
python motor_vr.py --cert certs/cert.pem --key certs/key.pem --webrtc-url https:/10.10.129.149:60001/offer
```
`--webrtc-url` はQuest自身がアクセスするURLです。`localhost` や `127.0.0.1` ではなくUbuntuのLAN IPを指定します。

Questのブラウザーで、まず以下のカメラページを開きます。証明書の警告を確認して接続を許可し、ページ内のStart操作で映像を確認します。

```text
https://192.168.0.20:60001/
```

確認後、次のVR画面を開きXRモードに入ります。周囲が見える状態で中央にカメラ映像を表示します。

```bash
https://10.10.129.149:8012/?ws=wss://10.10.129.149:8012
```

通常のUSBカメラには `--binocular` を付けません。左右を横並びにしたステレオ映像は別設定が必要です。現在の受信サンプルの映像サイズ指定も640×480固定なので、ステレオ用にはサイズ・表示比率の調整が必要です。

## 7. ファイアウォールとネットワーク

UFWを使っている場合は状態を確認し、必要なHTTPSポートを許可します。

```bash
sudo ufw status
sudo ufw allow 8012/tcp
sudo ufw allow 60001/tcp
```

8012はVRのHTTPS／WebSocket、60001はカメラのHTTPS／WebRTCシグナリングです。WebRTCの映像は別途動的なUDPポートを使用します。ページだけ表示され映像が出ない場合は、Ubuntu側やネットワーク側でQuestとのUDP通信が遮断されていないか確認します。この実装はWebRTCのUDP範囲を固定していないため、上のTCP許可だけでは映像通信を保証できません。

同一LAN内で使用してください。ゲストWi-Fiや端末間通信を遮断するアクセスポイントでは接続できない場合があります。PC内だけでZMQ映像確認する場合、55555等をLANへ開放する必要はありません。

## 8. よくある問題

| 症状 | 確認・対処 |
| --- | --- |
| `conda: command not found` | Miniforge導入後にターミナルを開き直す。第2節の `source` でも読み込み可能 |
| `CondaToSNonInteractiveError` | 第3節の `--override-channels -c conda-forge` 付きコマンドを使う |
| `EnvironmentLocationNotFound` | 環境作成の完了を確認。`conda env list` で `bool_robot` を確認 |
| `cannot import name 'Flag'` / `cannot import name 'Vuer'` | 最新のこのフォルダーを使い `python -m pip install -e ./xr_communication_only/televuer` を再実行。params-proto 2.13.2を使用 |
| `No module named uvc` | conda環境と `[server]` のインストールを確認 |
| カメラがない／開けない | `v4l2-ctl --list-devices`、videoグループ反映、他アプリの使用、`video_id` の引用符を確認 |
| カメラが黒い／fpsが合わない | `--list-formats-ext` の対応解像度・fpsへ設定を変更 |
| 証明書が見つからない | プロジェクト直下で実行し、`ls -l certs` と環境変数を確認 |
| Questでページが開かない | UbuntuのIP、同一LAN、ファイアウォール、証明書の受け入れを確認 |
| VR入力は動くが映像が出ない | 60001のページ単独で映像確認し、`/offer` URL、証明書、WebRTC用UDP通信を確認 |

毎回の起動では環境作成やインストールを繰り返さず、各ターミナルで `conda activate bool_robot` と `cd ~/bool_robot` を実行して、必要なサーバーを起動します。

## 動作確認の範囲・参考資料

この手順は同梱のソースコードと依存設定を確認して作成しました。Ubuntu上のインストール、実USBカメラ、Questとの接続は未確認です。Ubuntuのバージョン・CPU・カメラによって追加調整が必要な場合があります。

- [Miniforge公式インストール手順](https://github.com/conda-forge/miniforge)
- [conda-forgeの環境作成](https://conda-forge.org/docs/user/transitioning_from_defaults/)
- [pyuvc公式のLinux依存関係・USB権限](https://github.com/pupil-labs/pyuvc)
- [抽出版の説明](xr_communication_only/README_ja.md)
- [同梱TeleImagerのREADME](xr_communication_only/teleimager/README.md)

上流READMEにはUnitree向けの設定や、この抽出に含まれないスクリプトへの言及があります。まず本READMEのローカルパッケージ向け手順を使用してください。
