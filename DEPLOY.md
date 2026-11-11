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

## Quản trị

Trang quản trị nằm tại `/admin`. Bản này dùng 1 tài khoản, không cần database. Tài khoản và các phiên đăng nhập nằm trong `persistent/app/admin.json`, được ghi với quyền `0600`; mật khẩu lưu bằng scrypt, mã phiên chỉ lưu dạng băm. File này phải ở ngoài Git.

Tạo tài khoản dưới user chạy ứng dụng, trong thư mục repository:

```sh
.venv/bin/python -m kokorotts.admin_auth create --username admin --path persistent/app/admin.json
```

Lệnh yêu cầu nhập mật khẩu 2 lần, tối thiểu 12 ký tự. Có thể dùng `--generate` để tạo mật khẩu ngẫu nhiên; thông tin đăng nhập được ghi vào file `persistent/app/admin-initial.txt` với quyền `0600`. Cất thông tin này ở nơi riêng sau khi đã đăng nhập.

Đặt lại tài khoản/mật khẩu bằng terminal:

```sh
.venv/bin/python -m kokorotts.admin_auth reset --username admin --path persistent/app/admin.json
```

Đặt lại mật khẩu thu hồi toàn bộ phiên cũ. Phiên đăng nhập có thời hạn 8 giờ, dùng cookie HttpOnly/SameSite Strict và thêm Secure trên HTTPS. Đăng nhập bằng HTTP chỉ được chấp nhận từ loopback tại localhost để phát triển local. Các yêu cầu thay đổi cấu hình cần mã CSRF và phải cùng nguồn với trang quản trị.

Nếu dùng `KOKOROTTS_ADMIN_PATH` hoặc đặt file cấu hình runtime ở nơi khác, truyền `--path` đúng với đường dẫn tài khoản mà ứng dụng sử dụng. Không có tài khoản tạo sẵn, mật khẩu mặc định hay chức năng tạo tài khoản qua web.

Trang đọc công khai không yêu cầu tài khoản. Trình duyệt gọi `/web/tts/*` qua phiên web ẩn danh có chữ ký, cookie HttpOnly/SameSite Strict và kiểm tra Fetch Metadata/Origin. Cookie web không cấp quyền quản trị. Kịch bản khách được lưu riêng theo phiên trong `persistent/app/scripts/visitors/`, tách khỏi thư viện quản trị và API nội bộ. Mất cookie phiên đồng nghĩa không còn truy cập được thư viện khách cũ.

Trang admin và các chức năng `/web/system/*`, `/web/v1/*`, tài liệu API vẫn cần phiên admin; thao tác quản trị giữ kiểm tra CSRF. Tài liệu trình duyệt dùng `/web/tts/docs`, với schema chỉ dẫn đường gọi `/web`, không thay đổi schema API gốc.

Cấu hình Nginx ở `deploy/giongdoc.solqi.net.conf`. API gốc `/tts/*`, `/v1/*`, `/system/*`, MCP và health chỉ nhận loopback. Backend của mọi website cùng VPS gọi `http://127.0.0.1:7860`; xác thực riêng của API quản trị/OpenAI vẫn giữ nguyên. Nếu muốn dùng URL HTTPS `https://giongdoc.solqi.net/tts/...` ngay trong VPS, thêm `127.0.0.1 giongdoc.solqi.net` vào `/etc/hosts` để cuộc gọi đi thẳng tới Nginx cùng máy thay vì qua Cloudflare. Trình duyệt của website khác không được gọi API gốc hoặc gateway chéo nguồn; website đó phải gọi qua backend của mình.

Phiên web dùng khóa riêng `persistent/app/web-session.key`, quyền `0600`, không đưa lên Git. HTML và phản hồi gateway có `Cache-Control: private, no-store`; JavaScript đầu vào gắn phiên bản theo nội dung để không giữ mã giao tiếp cũ trong cache. Nginx không bật CORS công khai.

Sao lưu cấu hình Nginx cũ bên ngoài các thư mục đang include, sau đó cài cấu hình bằng root:

```sh
install -m 0644 deploy/giongdoc.solqi.net.conf /etc/nginx/sites-available/giongdoc.solqi.net.conf
nginx -t && systemctl reload nginx
```

Web công khai không thể ngăn tuyệt đối tool giả lập đầy đủ trình duyệt. Cơ chế này khóa API gốc, chặn gọi chéo nguồn, kiểm tra phiên web và giữ riêng quyền quản trị; đây không phải cơ chế chống bot tuyệt đối.

`KOKOROTTS_API_KEY` vẫn chỉ áp dụng cho API tương thích OpenAI, không thay thế đăng nhập quản trị. MCP giữ cơ chế và phạm vi truy cập nội bộ của bản nguồn; không công khai MCP qua reverse proxy.
