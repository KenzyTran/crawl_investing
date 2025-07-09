# Crawl Investing API

API Flask trả về toàn bộ HTML của một URL bất kỳ, sử dụng cloudscraper để vượt qua JS challenge.

## Yêu cầu hệ thống
- Python 3.8+
- Linux (tested on Amazon Linux 2023)

## Cài đặt
1. Clone repo về máy chủ:
   ```bash
   git clone <repo_url>
   cd crawl_investing
   ```
2. Cài đặt thư viện:
   ```bash
   pip install -r requirements.txt
   ```

## Chạy API (chế độ development)
```bash
python3 app.py
```
- Mặc định chạy trên http://127.0.0.1:5000
- Để truy cập từ bên ngoài, sửa dòng cuối file `app.py` thành:
  ```python
  if __name__ == '__main__':
      app.run(debug=True, host="0.0.0.0")
  ```

## Chạy nền trên server
```bash
nohup python3 app.py > log.txt 2>&1 &
```
- Để kiểm tra tiến trình: `ps aux | grep app.py`
- Để dừng: `kill <PID>`

## Gọi API
- Endpoint: `/get_html`
- Method: `GET`
- Tham số: `url` (bắt buộc)

Ví dụ:
```
curl "http://<ip-server>:5000/get_html?url=https://example.com"
```

## Lưu ý
- Nếu dùng production, nên triển khai với gunicorn + nginx hoặc systemd.
- Đảm bảo mở port 5000 trên firewall nếu truy cập từ bên ngoài.

## requirements.txt
```
cloudscraper
flask
```

## Liên hệ
- Nếu gặp lỗi 404, kiểm tra lại endpoint và tham số url.
- Nếu cần hướng dẫn production, liên hệ admin.
