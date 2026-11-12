"""Endpoint masuk, akun sendiri, dan peninjauan hasil deteksi.

Setiap endpoint melayani satu use case pada BAB III: login, melihat dashboard, melihat daftar hasil deteksi,
melihat detail hasil deteksi beserta kontribusi fitur (SHAP), dan mencatat tindak lanjut. Foto akun
melengkapi tampilan identitas pada halaman Akun dan kelola akun.
"""
import json
import os

from flask import Blueprint, current_app, g, jsonify, request, send_from_directory
from sqlalchemy import func
from werkzeug.security import check_password_hash

from .auth import buat_token, galat, wajib_masuk
from .ekstensi import db
from .layanan import model_deteksi, rujukan
from .models import (KEPUTUSAN, PANEL, STATUS_DETEKSI, HasilDeteksi, LogSinkronisasi, Pengguna, ProfilHasil,
                     TindakLanjut)

bp = Blueprint('api', __name__, url_prefix='/api')


@bp.post('/auth/masuk')
def masuk():
    data = request.get_json(silent=True) or {}
    username = str(data.get('username', '')).strip().lower()
    kata_sandi = str(data.get('kata_sandi', ''))
    if not username or not kata_sandi:
        return galat('Username dan kata sandi wajib diisi.', 400)
    p = Pengguna.query.filter_by(username=username).first()
    if p is None or not check_password_hash(p.kata_sandi, kata_sandi):
        return galat('Username atau kata sandi salah.', 401)
    if not p.status_aktif:
        return galat('Akun tidak aktif. Hubungi admin.', 403)
    return jsonify({'token': buat_token(p), 'pengguna': p.ke_dict()})


@bp.get('/auth/saya')
@wajib_masuk()
def saya():
    return jsonify(g.pengguna.ke_dict())


@bp.get('/pengguna/<int:id_pengguna>/foto')
@wajib_masuk()
def foto_pengguna(id_pengguna):
    """Foto akun (dari data pegawai SiLAKES). Petugas hanya dapat membuka fotonya sendiri; admin semua akun
    karena foto ditampilkan pada halaman kelola akun."""
    if g.pengguna.id_pengguna != id_pengguna and g.pengguna.peran != 'admin':
        return galat('Foto akun lain hanya dapat dibuka admin.', 403)
    p = db.session.get(Pengguna, id_pengguna)
    if p is None or not p.foto:
        return galat('Akun ini belum memiliki foto.', 404)
    return send_from_directory(current_app.config['FOLDER_FOTO'], p.foto, max_age=0)


def sinkronisasi_terakhir():
    """Sinkronisasi berhasil terakhir beserta jumlah profil per status yang dideteksi pada sinkronisasi itu."""
    log = (LogSinkronisasi.query.filter_by(status='berhasil')
           .order_by(LogSinkronisasi.waktu_selesai.desc()).first())
    if log is None:
        return None
    jumlah = dict(db.session.query(HasilDeteksi.status_deteksi, func.count())
                  .filter(HasilDeteksi.waktu_deteksi >= log.waktu_mulai,
                          HasilDeteksi.waktu_deteksi <= log.waktu_selesai)
                  .group_by(HasilDeteksi.status_deteksi))
    return {**log.ke_dict(), 'perlu_ditinjau': jumlah.get('perlu_ditinjau', 0),
            'tidak_ada_indikasi': jumlah.get('tidak_ada_indikasi', 0)}


def ringkas_deteksi(h):
    p = h.profil
    return {'id_deteksi': h.id_deteksi, 'peluang_anomali': float(h.peluang_anomali),
            'status_deteksi': h.status_deteksi, 'waktu_deteksi': h.waktu_deteksi.isoformat(timespec='seconds'),
            'profil': {'id_surat_silakes': p.id_surat_silakes, 'kode_pasien': p.kode_pasien,
                       'tanggal_periksa': p.tanggal_periksa.isoformat(), 'jenis_kelamin': p.jenis_kelamin,
                       'umur': p.umur}}


@bp.get('/ringkasan')
@wajib_masuk()
def ringkasan():
    jumlah = dict(db.session.query(HasilDeteksi.status_deteksi, func.count()).group_by(HasilDeteksi.status_deteksi))
    sudah = db.session.query(func.count(func.distinct(TindakLanjut.id_deteksi))).scalar() or 0
    terbaru = (HasilDeteksi.query.filter_by(status_deteksi='perlu_ditinjau')
               .order_by(HasilDeteksi.waktu_deteksi.desc(), HasilDeteksi.peluang_anomali.desc()).limit(3).all())
    return jsonify({'total': sum(jumlah.values()), 'perlu_ditinjau': jumlah.get('perlu_ditinjau', 0),
                    'tidak_ada_indikasi': jumlah.get('tidak_ada_indikasi', 0), 'sudah_ditindaklanjuti': sudah,
                    'sinkronisasi_terakhir': sinkronisasi_terakhir(),
                    'terbaru_perlu_ditinjau': [ringkas_deteksi(h) for h in terbaru]})


@bp.get('/deteksi')
@wajib_masuk()
def daftar_deteksi():
    status = request.args.get('status', '')
    cari = request.args.get('cari', '').strip().lower().replace('-', '').replace('#', '')
    try:
        halaman = max(1, int(request.args.get('halaman', 1)))
        per_halaman = min(100, max(1, int(request.args.get('per_halaman', 20))))
    except ValueError:
        return galat('Parameter halaman tidak valid.', 400)
    if status and status not in STATUS_DETEKSI:
        return galat('Status tidak dikenal.', 400)

    q = HasilDeteksi.query.join(ProfilHasil)
    if cari:
        syarat = ProfilHasil.kode_pasien.like(cari + '%')
        if cari.isdigit():
            syarat = syarat | (ProfilHasil.id_surat_silakes == int(cari))
        q = q.filter(syarat)
    # Jumlah per status untuk cip saringan dihitung sebelum saringan status diterapkan.
    jumlah = dict(q.with_entities(HasilDeteksi.status_deteksi, func.count()).group_by(HasilDeteksi.status_deteksi))
    if status:
        q = q.filter(HasilDeteksi.status_deteksi == status)
    awal, akhir = q.with_entities(func.min(ProfilHasil.tanggal_periksa), func.max(ProfilHasil.tanggal_periksa)).one()
    total = q.count()
    isi = (q.order_by(HasilDeteksi.peluang_anomali.desc(), HasilDeteksi.id_deteksi.desc())
           .offset((halaman - 1) * per_halaman).limit(per_halaman).all())
    return jsonify({'total': total, 'halaman': halaman, 'per_halaman': per_halaman,
                    'jumlah_status': {'semua': sum(jumlah.values()), **{s: jumlah.get(s, 0) for s in STATUS_DETEKSI}},
                    'rentang_tanggal': [awal.isoformat() if awal else None, akhir.isoformat() if akhir else None],
                    'data': [ringkas_deteksi(h) for h in isi]})


def _master():
    path = current_app.config['BERKAS_MASTER']
    if not os.path.exists(path):
        return {}, []
    with open(path, encoding='utf-8') as f:
        isi = json.load(f)
    return isi.get('parameter', {}), isi.get('rujukan', [])


@bp.get('/deteksi/<int:id_deteksi>')
@wajib_masuk()
def detail_deteksi(id_deteksi):
    h = db.session.get(HasilDeteksi, id_deteksi)
    if h is None:
        return galat('Hasil deteksi tidak ditemukan.', 404)
    master, baris_rujukan = _master()
    p = h.profil
    panel = []
    for no, nama in enumerate(PANEL, start=1):
        nilai = float(getattr(p, nama))
        kelas = rujukan.klasifikasi(baris_rujukan, nama, nilai, p.jenis_kelamin, p.umur) if baris_rujukan else None
        panel.append({'no': no, 'parameter': nama, 'nilai': nilai, 'satuan': master.get(nama, {}).get('satuan'),
                      'rujukan': kelas['rujukan'] if kelas else master.get(nama, {}).get('nilai_rujukan'),
                      'keterangan': kelas['keterangan'] if kelas else None,
                      'kategori': kelas['kategori'] if kelas else None})
    kontribusi = [k.ke_dict() for k in h.kontribusi]
    try:
        nilai_dasar = model_deteksi.nilai_dasar(current_app.config['FOLDER_MODEL'], h.model.versi)
    except FileNotFoundError:
        nilai_dasar = None
    keluaran = None if nilai_dasar is None else nilai_dasar + sum(k['nilai_shap'] for k in kontribusi)
    return jsonify({'id_deteksi': h.id_deteksi, 'peluang_anomali': float(h.peluang_anomali),
                    'status_deteksi': h.status_deteksi, 'waktu_deteksi': h.waktu_deteksi.isoformat(timespec='seconds'),
                    'model': {'versi': h.model.versi, 'ambang': float(h.model.ambang)},
                    'profil': p.ke_dict(), 'panel': panel, 'kontribusi': kontribusi,
                    'nilai_dasar': nilai_dasar, 'keluaran_log_odds': keluaran})


@bp.post('/deteksi/<int:id_deteksi>/tindak-lanjut')
@wajib_masuk('petugas')
def catat_tindak_lanjut(id_deteksi):
    h = db.session.get(HasilDeteksi, id_deteksi)
    if h is None:
        return galat('Hasil deteksi tidak ditemukan.', 404)
    data = request.get_json(silent=True) or {}
    keputusan = data.get('keputusan')
    if keputusan not in KEPUTUSAN:
        return galat('Pilih salah satu keputusan.', 400)
    catatan = (data.get('catatan') or '').strip() or None
    if catatan and len(catatan) > 1000:
        return galat('Catatan paling banyak 1000 karakter.', 400)
    t = TindakLanjut(id_deteksi=id_deteksi, id_pengguna=g.pengguna.id_pengguna, keputusan=keputusan, catatan=catatan)
    db.session.add(t)
    db.session.commit()
    return jsonify(t.ke_dict()), 201
