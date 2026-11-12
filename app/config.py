import json
import os
import secrets

SINI = os.path.dirname(os.path.abspath(__file__))
INSTANCE = os.path.join(os.path.dirname(SINI), 'instance')


def _rahasia():
    """Kunci JWT dan garam kode pasien dibuat acak sekali, lalu disimpan di instance/rahasia.json.

    Berkas ini tidak ikut dibagikan (lihat .gitignore). Variabel lingkungan SECRET_KEY dan GARAM_PASIEN,
    bila diisi, menggantikan isi berkas.
    """
    path = os.path.join(INSTANCE, 'rahasia.json')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    os.makedirs(INSTANCE, exist_ok=True)
    isi = {'secret_key': secrets.token_hex(32), 'garam_pasien': secrets.token_hex(16)}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(isi, f)
    return isi


_R = _rahasia()


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or _R['secret_key']
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///' + os.path.join(INSTANCE, 'prototipe.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_MASA_BERLAKU_JAM = int(os.environ.get('JWT_MASA_BERLAKU_JAM', '8'))

    # Garam rahasia untuk kode pasien yang disamarkan. Tanpa garam yang sama, kode tidak dapat
    # dikembalikan ke ID pasien SiLAKES.
    GARAM_PASIEN = os.environ.get('GARAM_PASIEN') or _R['garam_pasien']

    FOLDER_MODEL = os.environ.get('FOLDER_MODEL') or os.path.join(INSTANCE, 'model')
    BERKAS_MASTER = os.path.join(INSTANCE, 'master_pemeriksaan.json')
    # Foto akun pengguna yang disalin dari data pegawai SiLAKES (perintah flask foto-silakes).
    FOLDER_FOTO = os.environ.get('FOLDER_FOTO') or os.path.join(INSTANCE, 'foto')

    # Sumber sinkronisasi: 'ssh' membaca SiLAKES produksi (sesi READ ONLY), 'berkas' membaca TSV lokal.
    SUMBER_SINKRON = os.environ.get('SUMBER_SINKRON', 'ssh')
    SILAKES_SSH_HOST = os.environ.get('SILAKES_SSH_HOST', 'produli-server')
    SILAKES_ENV = os.environ.get('SILAKES_ENV', '/var/www/api.silakes.labkesdasumenep.id/.env')
    BERKAS_SINKRON = os.environ.get('BERKAS_SINKRON', '')
    # Data sampai 31 Oktober 2026 dipakai untuk pelatihan model, sehingga prototipe memproses surat sesudahnya.
    SINKRON_SEJAK = os.environ.get('SINKRON_SEJAK', '2026-11-01')
