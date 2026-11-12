import json
import os
import shutil
from datetime import date

import click
from flask import Flask, jsonify
from sqlalchemy import inspect as sa_inspect, text
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash

from .config import Config
from .ekstensi import db


def create_app(konfigurasi=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if konfigurasi:
        app.config.update(konfigurasi)
    os.makedirs(app.config['FOLDER_MODEL'], exist_ok=True)
    os.makedirs(os.path.dirname(app.config['BERKAS_MASTER']), exist_ok=True)
    db.init_app(app)

    from . import api, api_admin
    app.register_blueprint(api.bp)
    app.register_blueprint(api_admin.bp)

    @app.errorhandler(HTTPException)
    def galat_http(e):
        return jsonify({'galat': e.description}), e.code

    @app.errorhandler(Exception)
    def galat_lain(e):
        app.logger.exception(e)
        return jsonify({'galat': 'Terjadi kesalahan pada server. Coba lagi atau hubungi admin.'}), 500

    daftar_perintah(app)
    return app


def daftar_perintah(app):
    from .models import ModelDeteksi, Pengguna

    @app.cli.command('init-db')
    def init_db():
        """Buat tabel basis data prototipe (tujuh tabel PDM). Aman dijalankan ulang pada basis data lama."""
        db.create_all()
        # basis data yang dibuat sebelum kolom penautan pegawai SiLAKES ada: tambahkan kolomnya tanpa mengubah data
        kolom = [k['name'] for k in sa_inspect(db.engine).get_columns('pengguna')]
        for nama, tipe in (('akun_silakes', 'VARCHAR(60)'), ('foto', 'VARCHAR(100)')):
            if nama not in kolom:
                with db.engine.begin() as kon:
                    kon.execute(text('ALTER TABLE pengguna ADD COLUMN %s %s' % (nama, tipe)))
                click.echo('Kolom pengguna.%s ditambahkan.' % nama)
        click.echo('Tabel dibuat: ' + ', '.join(sorted(db.metadata.tables)))

    @app.cli.command('foto-silakes')
    @click.option('--username', required=True, help='Username akun pada prototipe.')
    @click.option('--akun-silakes', required=True, help='Username pegawai yang sama pada SiLAKES.')
    def foto_silakes(username, akun_silakes):
        """Tautkan akun prototipe dengan data pegawai SiLAKES dan salin fotonya (baca saja).
        Dipakai untuk admin pertama; akun lain ditautkan admin dari form akun pada aplikasi."""
        from .layanan.foto_pegawai import simpan_foto
        from .layanan.sumber_silakes import GalatSumber, SumberSsh
        p = Pengguna.query.filter_by(username=username.lower()).first()
        if p is None:
            raise click.ClickException('Akun %s tidak ada pada basis data prototipe.' % username)
        c = app.config
        try:
            ukuran = simpan_foto(p, akun_silakes.lower(), SumberSsh(c['SILAKES_SSH_HOST'], c['SILAKES_ENV'],
                                                                   c['GARAM_PASIEN']), c['FOLDER_FOTO'])
        except GalatSumber as e:
            raise click.ClickException(str(e))
        db.session.commit()
        click.echo('Akun %s ditautkan ke pegawai SiLAKES %s; foto disalin (%d byte).'
                   % (p.username, akun_silakes.lower(), ukuran))

    @app.cli.command('buat-admin')
    @click.option('--username', required=True)
    @click.option('--nama', required=True)
    @click.option('--kata-sandi', envvar='KATA_SANDI_ADMIN', prompt=True, hide_input=True, confirmation_prompt=True)
    def buat_admin(username, nama, kata_sandi):
        """Buat akun admin pertama. Akun berikutnya dibuat dari aplikasi."""
        if len(kata_sandi) < 8:
            raise click.ClickException('Kata sandi paling sedikit 8 karakter.')
        if Pengguna.query.filter_by(username=username.lower()).first():
            raise click.ClickException('Username sudah dipakai.')
        db.session.add(Pengguna(username=username.lower(), nama=nama, peran='admin',
                                kata_sandi=generate_password_hash(kata_sandi)))
        db.session.commit()
        click.echo('Admin %s dibuat.' % username.lower())

    @app.cli.command('impor-model')
    @click.option('--ringkasan', 'path_ringkasan', required=True, type=click.Path(exists=True),
                  help='penelitian/hasil/ringkasan.json')
    @click.option('--skenario', default=None, help='S1, S2, atau S3. Bawaan: skenario_model_akhir pada ringkasan.')
    @click.option('--versi', default=None, help='Paling banyak 20 karakter.')
    def impor_model(path_ringkasan, skenario, versi):
        """Salin model hasil penelitian ke folder model dan jadikan model aktif."""
        with open(path_ringkasan, encoding='utf-8') as f:
            r = json.load(f)
        skenario = skenario or r.get('skenario_model_akhir')
        if skenario not in r.get('skenario', {}):
            raise click.ClickException('Skenario %s tidak ada pada ringkasan.' % skenario)
        sumber = os.path.join(os.path.dirname(os.path.abspath(path_ringkasan)), skenario, 'model.json')
        tanggal = date.fromtimestamp(os.path.getmtime(sumber))
        versi = versi or '%s-%s' % (skenario, tanggal.isoformat())
        if len(versi) > 20:
            raise click.ClickException('Versi paling banyak 20 karakter.')
        shutil.copyfile(sumber, os.path.join(app.config['FOLDER_MODEL'], versi + '.json'))
        m = ModelDeteksi.query.filter_by(versi=versi).first() or ModelDeteksi(versi=versi, ambang=0.5)
        m.tanggal_latih = tanggal
        m.roc_auc_validasi = round(r['skenario'][skenario]['roc_auc_validasi_terbaik'], 4)
        ModelDeteksi.query.update({'status_aktif': False})
        m.status_aktif = True
        db.session.add(m)
        db.session.commit()
        click.echo('Model %s aktif (ROC-AUC validasi %.4f, ambang %.3f).' % (versi, m.roc_auc_validasi, m.ambang))
