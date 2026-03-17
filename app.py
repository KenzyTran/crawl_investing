import cloudscraper
from flask import Flask, request, jsonify

app = Flask(__name__)

TEST_URL = "https://finance.vietstock.vn"


@app.route('/health', methods=['GET'])
def health():
    """Health check - thử fetch 1 URL để kiểm tra có bị chặn không."""
    try:
        scraper = cloudscraper.create_scraper()
        resp = scraper.get(TEST_URL, timeout=15)
        if resp.status_code == 200:
            return jsonify({'status': 'ok'}), 200
        return jsonify({'status': 'blocked', 'code': resp.status_code}), 503
    except Exception as e:
        return jsonify({'status': 'error', 'detail': str(e)}), 503


@app.route('/get_html', methods=['GET'])
def get_html():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'Missing url'}), 400
    scraper = cloudscraper.create_scraper()
    response = scraper.get(url)
    return jsonify({
        'status_code': response.status_code,
        'html': response.text
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)