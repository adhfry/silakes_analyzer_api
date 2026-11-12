"""Klasifikasi nilai panel terhadap rentang rujukan SiLAKES.

Logika ini adalah porting langsung dari App\\Services\\LabReferenceService (backend SiLAKES,
api-administrasi-labkesda), supaya penanda pada aplikasi sama dengan penanda yang dilihat petugas di SiLAKES:
  1. baris rujukan aktif diurutkan menurut sort_order;
  2. gender pada baris harus kosong atau sama dengan jenis kelamin pasien;
  3. bila baris memakai umur dalam hari, baris dilewati karena umur yang tersimpan berupa tahun
     (sama dengan SiLAKES ketika umur hari tidak tersedia);
  4. umur dalam tahun dicocokkan dengan batas inklusif;
  5. nilai dicocokkan dengan batas inklusif/eksklusif sesuai min_inclusive dan max_inclusive;
  6. baris pertama yang cocok dipakai; severity_rank 0 berarti dalam rujukan.
Data baris rujukan dibaca dari tabel reference_ranges SiLAKES (baca saja) pada saat sinkronisasi.
"""

# parameter panel penelitian -> parameter_key pada reference_ranges SiLAKES
KUNCI = {'kolesterol_total': 'cholesterol_total', 'hdl': 'hdl', 'ldl': 'ldl', 'trigliserida': 'trigliserida',
         'urea': 'urea', 'kreatinin': 'creatinine'}


def _angka(v):
    return None if v in (None, '', 'NULL') else float(v)


def _bool(v):
    return str(v).strip() in ('1', 'True', 'true')


def baris_dari_kueri(rows):
    """Ubah baris TSV reference_ranges menjadi dict bertipe."""
    hasil = []
    for r in rows:
        hasil.append({
            'parameter_key': r['parameter_key'], 'gender': None if r['gender'] in ('', 'NULL') else r['gender'],
            'age_min_years': _angka(r['age_min_years']), 'age_max_years': _angka(r['age_max_years']),
            'age_min_days': _angka(r['age_min_days']), 'age_max_days': _angka(r['age_max_days']),
            'value_min': _angka(r['value_min']), 'value_max': _angka(r['value_max']),
            'min_inclusive': _bool(r['min_inclusive']), 'max_inclusive': _bool(r['max_inclusive']),
            'category': r['category'], 'category_label': r['category_label'],
            'severity_rank': int(r['severity_rank']), 'sort_order': int(r['sort_order'])})
    return sorted(hasil, key=lambda x: x['sort_order'])


def _umur_cocok(b, umur):
    if b['age_min_days'] is not None or b['age_max_days'] is not None:
        return False
    if b['age_min_years'] is not None and umur < b['age_min_years']:
        return False
    if b['age_max_years'] is not None and umur > b['age_max_years']:
        return False
    return True


def _nilai_cocok(b, nilai):
    if b['value_min'] is not None:
        if (nilai < b['value_min']) if b['min_inclusive'] else (nilai <= b['value_min']):
            return False
    if b['value_max'] is not None:
        if (nilai > b['value_max']) if b['max_inclusive'] else (nilai >= b['value_max']):
            return False
    return True


def _pita(baris, parameter, jenis_kelamin, umur):
    kunci = KUNCI[parameter]
    return [b for b in baris if b['parameter_key'] == kunci and b['gender'] in (None, jenis_kelamin)
            and _umur_cocok(b, umur)]


def _angka_id(v):
    return ('%.3f' % v).rstrip('0').rstrip('.').replace('.', ',')


def label_nilai(b):
    """Sama dengan formatValueLabel SiLAKES, tanpa satuan."""
    if b['value_min'] is not None and b['value_max'] is not None:
        return '%s - %s' % (_angka_id(b['value_min']), _angka_id(b['value_max']))
    if b['value_min'] is not None:
        return ('>= ' if b['min_inclusive'] else '> ') + _angka_id(b['value_min'])
    if b['value_max'] is not None:
        return ('<= ' if b['max_inclusive'] else '< ') + _angka_id(b['value_max'])
    return '-'


def klasifikasi(baris, parameter, nilai, jenis_kelamin, umur):
    """Kembalikan dict {rujukan, keterangan, kategori} atau None bila tidak ada pita yang cocok.

    rujukan    : rentang pita dengan severity_rank 0 (dalam rujukan) untuk jenis kelamin dan umur pasien
    keterangan : 'sesuai' bila pita yang cocok ber-severity 0, 'rendah' bila nilai di bawah pita rujukan,
                 'tinggi' bila di atasnya
    kategori   : category_label SiLAKES dari pita yang cocok
    """
    pita = _pita(baris, parameter, jenis_kelamin, umur)
    if not pita:
        return None
    normal = next((b for b in pita if b['severity_rank'] == 0), None)
    cocok = next((b for b in pita if _nilai_cocok(b, nilai)), None)
    if cocok is None:
        return None
    if cocok['severity_rank'] == 0:
        ket = 'sesuai'
    elif normal is not None and normal['value_min'] is not None and nilai < normal['value_min']:
        ket = 'rendah'
    else:
        ket = 'tinggi'
    return {'rujukan': label_nilai(normal) if normal else None, 'keterangan': ket,
            'kategori': cocok['category_label']}
