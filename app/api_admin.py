"""Endpoint admin sesuai use case admin pada BAB III: melihat dashboard, mengelola akun pengguna,
mengatur ambang deteksi, dan menjalankan sinkronisasi data (yang mencakup deteksi anomali)."""
import re

from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.security import generate_password_hash

from .api import sinkronisasi_terakhir
from .auth import galat, wajib_masuk
from .ekstensi import db
from .layanan import sinkronisasi
from .layanan.foto_pegawai import simpan_foto
from .layanan.sumber_silakes import GalatSumber, SumberBerkas, SumberSsh
from .models import PERAN, ModelDeteksi, Pengguna

bp = Blueprint('admin', __name__, url_prefix='/api/admin')
_USERNAME = re.compile(r'^[a-z0-9._]{3,50}$')
_AKUN_SILAKES = re.compile(r'^[a-z0-9._@-]{3,60}$')


@bp.get('/ringkasan')
@wajib_masuk('admin')
def ringkasan():
    model = ModelDeteksi.query.filter_by(status_aktif=True).first()
    return jsonify({'model_aktif': model.ke_dict() if model else None,
                    'sinkronisasi_terakhir': sinkronisasi_terakhir(),
                    'pengguna_aktif': Pengguna.query.filter_by(status_aktif=True).count()})


@bp.get('/pengguna')
@wajib_masuk('admin')
def daftar_pengguna():
    return jsonify([p.ke_dict() for p in Pengguna.query.order_by(Pengguna.peran, Pengguna.nama).all()])


def _periksa(data, baru):
    """Kembalikan pesan galat pertama, atau None bila data akun valid."""
    if baru or 'nama' in data:
        nama = str(data.get('nama', '')).strip()
        if not 1 <= len(nama) <= 100:
            return 'Nama wajib diisi, paling banyak 100 karakter.'
    if baru or 'username' in data:
        if not _USERNAME.match(str(data.get('username', '')).strip().lower()):
            return 'Username 3 sampai 50 karakter: huruf kecil, angka, titik, atau garis bawah.'
    if baru or 'peran' in data:
        if data.get('peran') not in PERAN:
            return 'Peran harus petugas atau admin.'
    if baru or data.get('kata_sandi'):
        if len(str(data.get('kata_sandi', ''))) < 8:
            return 'Kata sandi paling sedikit 8 karakter.'
    if 'status_aktif' in data and not isinstance(data['status_aktif'], bool):
        return 'Status aktif harus true atau false.'
    akun = str(data.get('akun_silakes') or '').strip().lower()
    if akun and not _AKUN_SILAKES.match(akun):
        return 'Username SiLAKES 3 sampai 60 karakter: huruf kecil, angka, titik, garis bawah, minus, atau @.'
    return None


def _tautkan(p, akun):
    """Ambil foto pegawai SiLAKES untuk akun p. Mengembalikan pesan galat, atau None bila berhasil."""
    try:
        simpan_foto(p, akun, buat_sumber(), current_app.config['FOLDER_FOTO'])
    except GalatSumber as e:
        return str(e)
    return None


@bp.post('/pengguna')
@wajib_masuk('admin')
def tambah_pengguna():
    data = request.get_json(silent=True) or {}
    pesan = _periksa(data, baru=True)
    if pesan:
        return galat(pesan, 400)
    username = data['username'].strip().lower()
    if Pengguna.query.filter_by(username=username).first():
        return galat('Username sudah dipakai.', 409)
    p = Pengguna(nama=data['nama'].strip(), username=username, peran=data['peran'],
                 kata_sandi=generate_password_hash(data['kata_sandi']), status_aktif=data.get('status_aktif', True))
    akun = str(data.get('akun_silakes') or '').strip().lower()
    if akun:
        pesan = _tautkan(p, akun)
        if pesan:
            return galat(pesan, 400)
    db.session.add(p)
    db.session.commit()
    return jsonify(p.ke_dict()), 201


@bp.put('/pengguna/<int:id_pengguna>')
@wajib_masuk('admin')
def ubah_pengguna(id_pengguna):
    p = db.session.get(Pengguna, id_pengguna)
    if p is None:
        return galat('Pengguna tidak ditemukan.', 404)
    data = request.get_json(silent=True) or {}
    pesan = _periksa(data, baru=False)
    if pesan:
        return galat(pesan, 400)
    # Admin tidak boleh mengunci dirinya sendiri dari menu admin.
    if p.id_pengguna == g.pengguna.id_pengguna and (data.get('status_aktif') is False or
                                                    data.get('peran', 'admin') != 'admin'):
        return galat('Admin tidak dapat menonaktifkan atau menurunkan peran akunnya sendiri.', 400)
    if 'username' in data:
        username = data['username'].strip().lower()
        lain = Pengguna.query.filter_by(username=username).first()
        if lain and lain.id_pengguna != p.id_pengguna:
            return galat('Username sudah dipakai.', 409)
        p.username = username
    if 'nama' in data:
        p.nama = data['nama'].strip()
    if 'peran' in data:
        p.peran = data['peran']
    if 'status_aktif' in data:
        p.status_aktif = data['status_aktif']
    if data.get('kata_sandi'):
        # reset kata sandi oleh admin: kata sandi lama tidak diperlukan dan tidak pernah ditampilkan
        p.kata_sandi = generate_password_hash(data['kata_sandi'])
    if 'akun_silakes' in data:
        akun = str(data.get('akun_silakes') or '').strip().lower()
        if not akun:
            p.akun_silakes = None
        elif akun != p.akun_silakes or not p.foto:
            pesan = _tautkan(p, akun)
            if pesan:
                db.session.rollback()
                return galat(pesan, 400)
    db.session.commit()
    return jsonify(p.ke_dict())


@bp.get('/ambang')
@wajib_masuk('admin')
def lihat_ambang():
    model = ModelDeteksi.query.filter_by(status_aktif=True).first()
    if model is None:
        return galat('Belum ada model aktif.', 404)
    return jsonify(model.ke_dict())


@bp.put('/ambang')
@wajib_masuk('admin')
def ubah_ambang():
    model = ModelDeteksi.query.filter_by(status_aktif=True).first()
    if model is None:
        return galat('Belum ada model aktif.', 404)
    nilai = (request.get_json(silent=True) or {}).get('ambang')
    if isinstance(nilai, bool) or not isinstance(nilai, (int, float)) or not 0 <= nilai <= 1:
        return galat('Ambang harus angka antara 0,00 dan 1,00.', 400)
    model.ambang = round(float(nilai), 3)
    db.session.commit()
    return jsonify(model.ke_dict())


def buat_sumber():
    c = current_app.config
    if c['SUMBER_SINKRON'] == 'berkas':
        return SumberBerkas(c['BERKAS_SINKRON'], c.get('FOLDER_FOTO_UJI'))
    return SumberSsh(c['SILAKES_SSH_HOST'], c['SILAKES_ENV'], c['GARAM_PASIEN'])


@bp.post('/sinkronisasi')
@wajib_masuk('admin')
def jalankan_sinkronisasi():
    c = current_app.config
    try:
        hasil = sinkronisasi.jalankan(buat_sumber(), g.pengguna, c['FOLDER_MODEL'], c['SINKRON_SEJAK'],
                                      c['BERKAS_MASTER'])
    except sinkronisasi.GalatSinkronisasi as e:
        return galat(str(e), e.kode)
    return jsonify(hasil)
