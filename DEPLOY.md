# Triển khai Giọng đọc

Mã nguồn được sao chép từ KokoroTTS tại commit `8a0b533`. Gốc repository là thư mục ứng dụng, chứa `kokorotts/`, `assets/` và `ecosystem.config.cjs`.

Git lưu mã nguồn, giao diện, tài liệu, bộ kiểm thử và các file khai báo thư viện. Model, audio mẫu, dữ liệu phát sinh và `.venv` được lưu riêng. Workflow phát hành Docker của dự án gốc không được đưa sang repository này.

## Dữ liệu đi kèm

Hai file nằm cạnh thư mục repository, không đưa lên Git:

- `giongdoc-runtime-data.zip`: cache model của 5 nhóm giọng và các audio mẫu trong `examples/`.
- `giongdoc-runtime-data.zip.sha256`: mã kiểm tra file ZIP.

Sau khi chuyển 2 file lên VPS, kiểm tra và giải nén tại thư mục ứng dụng:

```sh
sha256sum -c giongdoc-runtime-data.zip.sha256
unzip giongdoc-runtime-data.zip -d /duong-dan/toi/giongdoc
```

Model được đặt tại `persistent/models/huggingface/hub/`. File cấu hình PM2 đã đặt `HF_HOME` tương ứng. Các liên kết bên trong cache dùng đường dẫn tương đối; giải nén bằng `unzip` trên Linux để giữ các liên kết này.

## Cài môi trường lần đầu

Máy chủ cần Python 3.13, môi trường `venv`, trình biên dịch, `ffmpeg` và `espeak-ng`. Tạo `.venv` ngay trong thư mục ứng dụng:

```sh
cd /duong-dan/toi/giongdoc
python3.13 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e . --no-deps
.venv/bin/python -m pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
```

`requirements.txt` giữ nguyên bộ thư viện đang dùng ở bản nguồn, bao gồm Torch và nguồn wheel CUDA 13. Chọn bộ Torch phù hợp phần cứng VPS nếu cần thay đổi cấu hình chạy. ZIP dữ liệu không thay thế bước cài thư viện.

Nếu sử dụng tiếng Nhật, cài bộ từ điển theo đúng phiên bản trong Dockerfile:

```sh
.venv/bin/python scripts/install_open_jtalk_dictionary.py --version 1.11 --url https://github.com/r9y9/open_jtalk/releases/download/v1.11.1/open_jtalk_dic_utf_8-1.11.tar.gz --sha256 fe6ba0e43542cef98339abdffd903e062008ea170b04e7e2a35da805902f382a
```

Sau khi cài PM2 và giải nén dữ liệu, chạy:

```sh
pm2 start ecosystem.config.cjs
```

Ứng dụng lắng nghe tại `127.0.0.1:7860`; cấu hình reverse proxy của VPS trỏ tới địa chỉ này. Các đường dẫn Python, model và dữ liệu trong cấu hình PM2 được tính theo vị trí repository. Điều chỉnh số luồng theo CPU của VPS.

## Cập nhật

Cập nhật mã bằng Git. Cài lại thư viện khi các file khai báo thư viện thay đổi. Sau khi sửa Python hoặc cấu hình chạy, khởi động lại tiến trình `kokorotts`. Giữ thư mục `persistent/` khi cập nhật mã nguồn.
