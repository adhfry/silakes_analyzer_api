from app import create_app

app = create_app()

if __name__ == '__main__':
    # Pengujian di jaringan lokal: ponsel dan laptop berada pada Wi-Fi yang sama.
    app.run(host='0.0.0.0', port=5000)
