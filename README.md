# Layanan REST API SiLAKES Analyzer (Flask)

Layanan ini menyimpan hasil deteksi pada basis data prototipe, yaitu tujuh tabel PDM BAB III (`pengguna`, `log_sinkronisasi`, `model_deteksi`, `profil_hasil`, `hasil_deteksi`, `kontribusi_fitur`, `tindak_lanjut`). Data dibaca dari SiLAKES dengan akses **baca saja**, lalu dilayani ke aplikasi Android di `sistem/mobile`.

## Menyiapkan

```bash
cd sistem/api
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
export FLASK_APP=wsgi.py
.venv/Scripts/python.exe -m flask init-db
.venv/Scripts/python.exe -m flask impor-model --ringkasan ../../penelitian/hasil/ringkasan.json
.venv/Scripts/python.exe -m flask buat-admin --username ahda --nama "Ahda Firly Barori"
.venv/Scripts/python.exe -m flask foto-silakes --username ahda --akun-silakes ahda@labkesmas
.venv/Scripts/python.exe wsgi.py          # http://0.0.0.0:5000
```

Langkah-langkah di atas:

- `impor-model` menyalin `penelitian/hasil/<skenario>/model.json` dari skenario yang tercatat sebagai `skenario_model_akhir` (S2, 80:10:10), lalu menjadikannya model aktif dengan ambang 0,50.
- Pada saat pertama kali layanan dijalankan, kunci JWT dan garam kode pasien dibuat acak. Keduanya disimpan di `instance/rahasia.json`. Berkas ini jangan dibagikan. Bila garam berubah, kode pasien yang baru tidak akan cocok dengan kode lama.
- `buat-admin` membuat admin pertama, karena belum ada admin yang dapat membuatnya dari aplikasi. `foto-silakes` menautkan akun itu ke data pegawai SiLAKES dan menyalin fotonya (baca saja). Akun berikutnya dibuat admin dari aplikasi: form tambah akun memiliki isian *username* pegawai SiLAKES, dan layanan mengambil fotonya saat akun disimpan.
- `init-db` aman dijalankan ulang pada basis data lama; kolom `pengguna.akun_silakes` dan `pengguna.foto` ditambahkan bila belum ada.
- Aplikasi Android menerima alamat layanan saat dibangun (`--dart-define=API_URL=...`). Emulator memakai `http://10.0.2.2:5000`, yaitu alamat laptop dari dalam emulator.

## Sumber sinkronisasi

| Variabel | Bawaan | Arti |
|---|---|---|
| `SUMBER_SINKRON` | `ssh` | `ssh`: membaca SiLAKES produksi melalui host SSH. `berkas`: membaca TSV lokal (dipakai pytest). |
| `SILAKES_SSH_HOST` | `produli-server` | Nama host pada `~/.ssh/config`, memakai kunci SSH. Kata sandi server tidak disimpan di mana pun. Isi `lokal` bila layanan berjalan di server SiLAKES sendiri (produksi): perintah baca yang sama dijalankan tanpa SSH. |
| `SINKRON_SEJAK` | `2026-11-01` | Data sampai 31 Oktober 2026 dipakai untuk melatih model, sehingga basis data prototipe hanya memproses surat sesudah tanggal itu. Basis data uji black box memakai `2026-10-01`. |
| `DATABASE_URL` | SQLite `instance/prototipe.db` | Basis data uji: `sqlite:///D:/SKRIPSI_AHDA/sistem/api/instance/pengujian.db`. |

Pengamanan akses baca saja ada dua lapis:

1. Setiap sesi MySQL dibuka dengan `SET SESSION TRANSACTION READ ONLY`, sehingga server basis data menolak semua perintah tulis.
2. Sebelum dikirim, kueri diperiksa oleh `periksa_baca_saja`. Kueri yang memuat kata perintah tulis ditolak.

Bukti kedua lapis ada di `bukti_pengujian/bukti_akses_baca_saja.txt`.

Data yang diambil hanya:

- nomor surat;
- kode pasien hasil SHA-256 dengan garam (nama, NIK, alamat, telepon, dan tanggal lahir tidak dibaca);
- tanggal;
- jenis kelamin;
- umur;
- enam nilai panel;
- satuan dan baris nilai rujukan dari tabel parameter SiLAKES;
- untuk akun yang ditautkan: kolom `users.foto` dan berkas fotonya di `storage/app/public/foto/` (dibaca dengan `cat`). Nomor induk pegawai, telepon, dan alamat pegawai tidak dibaca.

Sinkronisasi bersifat bertahap. Setelah sinkronisasi berhasil, sinkronisasi berikutnya hanya membaca surat yang `updated_at`-nya tidak lebih awal dari waktu mulai sinkronisasi terakhir dikurangi 5 menit. Surat yang sudah tersimpan tidak dihitung ulang sebagai surat baru. Bila tidak ada surat baru, ringkasan sinkronisasi memberi tanda `ada_data_baru: false`.

Kolom Rujukan dan Ket pada detail hasil dihitung dengan aturan yang sama seperti `LabReferenceService` SiLAKES (`app/layanan/rujukan.py`):

- baris dicocokkan berdasarkan jenis kelamin;
- baris rujukan berbasis umur dalam hari dilewati;
- batas umur dalam tahun bersifat inklusif;
- baris pertama yang cocok menurut `sort_order` dipakai.

## Endpoint

| Metode | Jalur | Peran | Isi |
|---|---|---|---|
| POST | `/api/auth/masuk` | umum | `{username, kata_sandi}` → `{token, pengguna}`. Token JWT berlaku 8 jam. |
| GET | `/api/auth/saya` | semua | akun yang sedang masuk |
| GET | `/api/ringkasan` | semua | jumlah per status, jumlah sudah ditindaklanjuti, tiga profil perlu ditinjau terbaru, sinkronisasi terakhir |
| GET | `/api/deteksi?status=&cari=&halaman=` | semua | daftar diurutkan dari peluang tertinggi, `jumlah_status` untuk cip saringan, `rentang_tanggal` |
| GET | `/api/deteksi/<id>` | semua | profil; panel dengan satuan, rujukan, dan keterangan; peluang; ambang; delapan kontribusi SHAP; nilai dasar; keluaran log-odds; riwayat tindak lanjut |
| POST | `/api/deteksi/<id>/tindak-lanjut` | petugas | `{keputusan, catatan}`, keputusan salah satu dari `hasil_sesuai`, `verifikasi_identitas_spesimen`, `pemeriksaan_ulang` |
| GET | `/api/admin/ringkasan` | admin | model aktif, ambang, sinkronisasi terakhir beserta jumlah perlu ditinjau dan tidak ada indikasi |
| GET, POST | `/api/admin/pengguna` | admin | daftar dan tambah akun; `akun_silakes` opsional menautkan akun ke pegawai SiLAKES dan mengambil fotonya (400 bila pegawai tidak ditemukan) |
| PUT | `/api/admin/pengguna/<id>` | admin | ubah nama, username, peran, status aktif, tautan pegawai SiLAKES, dan reset kata sandi (`kata_sandi` baru). Admin tidak dapat menonaktifkan atau menurunkan peran akunnya sendiri. |
| GET | `/api/pengguna/<id>/foto` | semua | foto akun; petugas hanya fotonya sendiri, admin semua akun |
| GET, PUT | `/api/admin/ambang` | admin | ambang model aktif, 0 sampai 1 |
| POST | `/api/admin/sinkronisasi` | admin | menjalankan sinkronisasi dan deteksi, mengembalikan ringkasan hasil |

Status akun diperiksa pada setiap permintaan. Token milik akun yang dinonaktifkan langsung ditolak dengan 401.

Status deteksi ditentukan dengan aturan yang sama seperti pada evaluasi penelitian (`penelitian/src/eksperimen.py`): profil dengan **peluang > ambang** diberi status `perlu_ditinjau`, selebihnya `tidak_ada_indikasi`.

Nilai dasar SHAP diambil setelah penjelas TreeSHAP menghitung satu prediksi. Sebelum itu, `expected_value` milik pustaka SHAP masih berupa taksiran dan selisihnya terhadap nilai dasar sebenarnya 0,0038.

## Produksi

Layanan produksi: `https://analyzer.silakes.labkesdasumenep.id`, di VPS yang sama dengan SiLAKES. Polanya mengikuti situs lain di VPS tersebut: nginx sebagai *reverse proxy*, sertifikat dari certbot, dan proses dijaga supervisor.

| Bagian | Lokasi di VPS |
|---|---|
| Kode (klon repo ini) | `/var/www/analyzer.silakes.labkesdasumenep.id` |
| Lingkungan Python | `.venv` di folder yang sama (Python 3.12) |
| Basis data prototipe, kunci, model, foto | `instance/`, milik `www-data`, tidak ada di repo |
| Proses | supervisor `silakes-analyzer` (`deploy/silakes-analyzer.conf`), gunicorn `127.0.0.1:5065` |
| Nginx | `deploy/analyzer.silakes.labkesdasumenep.id`, HTTPS ditambahkan certbot |
| Log | `/var/log/silakes-analyzer.log`, `/var/log/nginx/analyzer.silakes.*.log` |

Memperbarui kode:

```bash
cd /var/www/analyzer.silakes.labkesdasumenep.id
git pull
.venv/bin/pip install -r requirements.txt     # bila requirements berubah
sudo -u www-data env SILAKES_SSH_HOST=lokal .venv/bin/flask --app wsgi.py init-db   # bila tabel berubah
sudo supervisorctl restart silakes-analyzer
```

Perintah `flask` lain (misalnya `buat-admin`, `impor-model`) dijalankan dengan cara yang sama, sebagai `www-data` dan dengan `SILAKES_SSH_HOST=lokal`, agar berkas di `instance/` tetap milik proses layanan.

## Pengujian

```bash
.venv/Scripts/python.exe -m pytest -v
```

Rangkaian uji terdiri atas 18 uji:

1. login benar dan salah;
2. akun nonaktif ditolak;
3. tanpa token dan token rusak;
4. petugas tidak dapat membuka menu admin;
5. sinkronisasi mengikuti aturan persiapan data;
6. daftar, detail (termasuk sifat aditif SHAP), dan tindak lanjut;
7. admin mengelola pengguna;
8. token akun yang dinonaktifkan langsung ditolak;
9. admin tidak dapat mengunci dirinya sendiri;
10. ambang;
11. ringkasan admin memuat sinkronisasi terakhir;
12. klasifikasi rujukan sama dengan SiLAKES;
13. sinkronisasi tanpa surat baru;
14. status memakai aturan lebih dari ambang;
15. nilai dasar SHAP aditif sejak model dimuat;
16. kueri baca saja menolak kata perintah tulis;
17. akun baru ditautkan ke pegawai SiLAKES beserta fotonya, username SiLAKES yang tidak ada ditolak, dan reset kata sandi;
18. foto akun hanya untuk pemilik dan admin, dan kueri foto pegawai hanya membaca kolom foto.

Log terakhir: `bukti_pengujian/log_pytest_layanan.txt` (18 lulus). Pengujian black box di emulator dijelaskan pada `sistem/mobile/README.md`.
