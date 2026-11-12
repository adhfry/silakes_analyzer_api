from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import current_app, g, jsonify, request

from .ekstensi import db
from .models import Pengguna


def galat(pesan, kode):
    return jsonify({'galat': pesan}), kode


def buat_token(pengguna):
    sekarang = datetime.now(timezone.utc)
    isi = {'sub': str(pengguna.id_pengguna), 'peran': pengguna.peran, 'iat': sekarang,
           'exp': sekarang + timedelta(hours=current_app.config['JWT_MASA_BERLAKU_JAM'])}
    return jwt.encode(isi, current_app.config['SECRET_KEY'], algorithm='HS256')


def wajib_masuk(*peran):
    """Dekorator: token JWT harus sah, akun masih aktif, dan (bila diberikan) peran akun termasuk `peran`."""
    def bungkus(fungsi):
        @wraps(fungsi)
        def dalam(*args, **kwargs):
            kepala = request.headers.get('Authorization', '')
            if not kepala.startswith('Bearer '):
                return galat('Token tidak ada. Silakan masuk kembali.', 401)
            try:
                isi = jwt.decode(kepala[7:], current_app.config['SECRET_KEY'], algorithms=['HS256'])
            except jwt.ExpiredSignatureError:
                return galat('Sesi sudah berakhir. Silakan masuk kembali.', 401)
            except jwt.InvalidTokenError:
                return galat('Token tidak sah. Silakan masuk kembali.', 401)
            pengguna = db.session.get(Pengguna, int(isi['sub']))
            # Status akun diperiksa pada setiap permintaan agar akun yang dinonaktifkan admin langsung tertolak.
            if pengguna is None or not pengguna.status_aktif:
                return galat('Akun tidak aktif. Hubungi admin.', 401)
            if peran and pengguna.peran not in peran:
                return galat('Menu ini hanya untuk peran ' + ', '.join(peran) + '.', 403)
            g.pengguna = pengguna
            return fungsi(*args, **kwargs)
        return dalam
    return bungkus
