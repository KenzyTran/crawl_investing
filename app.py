import cloudscraper
from flask import Flask, request, jsonify

app = Flask(__name__)

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
    app.run(debug=True)