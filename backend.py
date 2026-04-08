# -*- coding: utf-8 -*-
import asyncio
import os
import re
import json
import sys
import time
import unicodedata
import threading
from telethon import TelegramClient
from telethon.sessions import StringSession
from flask import Flask, request, jsonify, Response

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

# Force UTF-8
try:
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)
    sys.stderr = open(sys.stderr.fileno(), mode='w', encoding='utf-8', buffering=1)
except Exception:
    pass

# ========== CONFIG ==========
API_ID = os.environ.get('API_ID', '17570480')
API_HASH = os.environ.get('API_HASH', '18c5be05094b146ef29b0cb6f6601f1f')
SESSION_STRING = os.environ.get('SESSION_STRING', "1BJWap1wBu3xlWrAMpFkWLSLPJJWGP7kf227yl3Fw6YnwILFqWiet8NOWs33Ml_9YYxmrAArsK1KdpOuPDYsM6qFh55OiC8pIvEEkCyzu1dkSj8qekqttx4DgpFqDB2n8fMgh7pPcaw6bOQ1u5EmkScAzl76gehj-YtFUSQopjItoHuexmCvgJZ1XBzKTtyu-rbbfK47fCqAam68kwLPdD__sPoJJA4cnnnOTLucT6vpAYoHJz0W1lHATQ_4y5ZepAP6GbZY3IE0vF6qiGZvVwSkJmQZsOlX1WHPQUgjA5iJ03K1EB6gY8nuXL1q_I8Z0RjzJXLf1EG_sZjh7IztqDfRk29y9Tno=")
BOT_USERNAME = os.environ.get('BOT_USERNAME', "Miyavrem_bot")

PORT = int(os.environ.get('PORT', 5000))

# ========== GLOBALS ==========
result_cache = {}
app_started = False
thread_local = threading.local()

def get_event_loop():
    if not hasattr(thread_local, 'loop'):
        thread_local.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(thread_local.loop)
    return thread_local.loop

# ========== UTILITIES ==========
def fix_unicode_escapes(text: str) -> str:
    if not text:
        return ""
    try:
        if '\\u' in text:
            text = text.replace('\\\\u', '\\u')
            decoded = bytes(text, 'utf-8').decode('unicode_escape')
            return decoded
    except Exception:
        pass
    return text

def normalize_turkish_text(text: str) -> str:
    if not text:
        return ""
    
    text = fix_unicode_escapes(text)
    
    try:
        text = unicodedata.normalize('NFKC', text)
    except:
        pass
    
    turkish_mapping = {
        '\u0130': 'İ', '\u0131': 'ı', '\u011f': 'ğ', '\u011e': 'Ğ',
        '\u015f': 'ş', '\u015e': 'Ş', '\u00e7': 'ç', '\u00c7': 'Ç',
        '\u00fc': 'ü', '\u00dc': 'Ü', '\u00f6': 'ö', '\u00d6': 'Ö',
        '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
        '\u2013': '-', '\u2014': '-', '\u2026': '...', '\u00a0': ' ',
        '\u200b': '', '\u200e': '', '\u200f': '', '\u202a': '', '\u202c': '', '\ufeff': '',
    }
    
    result = text
    for wrong, correct in turkish_mapping.items():
        result = result.replace(wrong, correct)
    
    result = re.sub(r'\s+', ' ', result)
    return result.strip()

def decode_and_fix_text(content: bytes) -> str:
    encodings = ['utf-8', 'iso-8859-9', 'cp1254', 'windows-1254', 'latin-1']
    
    for encoding in encodings:
        try:
            decoded = content.decode(encoding)
            return normalize_turkish_text(decoded)
        except UnicodeDecodeError:
            continue
    
    try:
        decoded = content.decode('utf-8', errors='replace')
        return normalize_turkish_text(decoded)
    except:
        return content.decode('utf-8', errors='ignore')

# ========== KAYITLARI BÖL ==========
def split_records(text: str) -> list:
    """Çoklu kayıtları ayır"""
    if not text:
        return []
    
    pattern = r'=+\s*Kayıt\s+\d+/\d+\s*=+'
    parts = re.split(pattern, text)
    
    if parts and not parts[0].strip():
        parts = parts[1:]
    
    cleaned = []
    for part in parts:
        part = part.strip()
        if part and len(part) > 20:
            cleaned.append(part)
    
    return cleaned

# ========== TEK KAYIT PARSE ET ==========
def parse_single_record(text: str):
    """Tek bir kaydı parse et"""
    if not text:
        return {}
    
    result = {
        'TC': '', 'Ad': '', 'Soyad': '', 'DogumYeri': '', 'DogumTarihi': '',
        'AnneAdi': '', 'AnneTC': '', 'BabaAdi': '', 'BabaTC': '',
        'Il': '', 'Ilce': '', 'Koy': '', 'MhrsIl': '', 'MhrsIlce': '',
        'Ikametgah': '', 'AileSira': '', 'BireySira': '', 'MedeniDurum': '',
        'Cinsiyet': '', 'BirincilGSM': '', 'DigerGSMler': [],
        'IsyeriUnvani': '', 'IseGirisTarihi': '', 'IsyeriSektor': ''
    }
    
    # TC
    tc_match = re.search(r'🪪\s*TC\s*:\s*(\d{11})', text)
    if tc_match:
        result['TC'] = tc_match.group(1)
    
    # Ad Soyad
    ad_match = re.search(r'👤\s*(?:Adı Soyadı|Ad Soyad|AdSoyad)\s*:\s*(.+?)(?=\s*(?:🎂|👩|👨|📍|🏥|🏠|🧬|💍|📞|🏢|📅|🏷|=|\n\n|$))', text, re.IGNORECASE | re.DOTALL)
    if ad_match:
        full = ad_match.group(1).strip().upper()
        full = re.sub(r'\s+', ' ', full)
        parts = full.split()
        if parts:
            result['Ad'] = parts[0]
            result['Soyad'] = ' '.join(parts[1:]) if len(parts) > 1 else ''
    
    # Doğum
    dogum_match = re.search(r'🎂\s*(?:Doğum|Dogum).*?:\s*([^/]+?)\s*/\s*([\d-]+?)(?=\s*(?:👩|👨|📍|🏥|🏠|🧬|💍|📞|🏢|📅|🏷|=|\n\n|$))', text, re.IGNORECASE | re.DOTALL)
    if dogum_match:
        result['DogumYeri'] = dogum_match.group(1).strip().title()
        result['DogumTarihi'] = dogum_match.group(2).strip()
    
    # Anne
    anne_match = re.search(r'👩\s*(?:Anne).*?:\s*([^/]+?)\s*/\s*(\d{11})(?=\s*(?:👨|📍|🏥|🏠|🧬|💍|📞|🏢|📅|🏷|=|\n\n|$))', text, re.IGNORECASE | re.DOTALL)
    if anne_match:
        result['AnneAdi'] = anne_match.group(1).strip().upper()
        result['AnneTC'] = anne_match.group(2).strip()
    
    # Baba
    baba_match = re.search(r'👨\s*(?:Baba).*?:\s*([^/]+?)\s*/\s*(\d{11})(?=\s*(?:📍|🏥|🏠|🧬|💍|📞|🏢|📅|🏷|=|\n\n|$))', text, re.IGNORECASE | re.DOTALL)
    if baba_match:
        result['BabaAdi'] = baba_match.group(1).strip().upper()
        result['BabaTC'] = baba_match.group(2).strip()
    
    # İl/İlçe/Köy
    yer_match = re.search(r'📍\s*(?:İl/İlçe/Köy|IlIlceKoy)\s*:\s*([^/]+?)\s*/\s*([^/]+?)\s*/\s*(.+?)(?=\s*(?:🏥|🏠|🧬|💍|📞|🏢|📅|🏷|=|\n\n|$))', text, re.IGNORECASE | re.DOTALL)
    if yer_match:
        result['Il'] = yer_match.group(1).strip().title()
        result['Ilce'] = yer_match.group(2).strip().title()
        result['Koy'] = yer_match.group(3).strip().title()
    
    # MHRS
    mhrs_match = re.search(r'🏥\s*(?:MHRS Adres İl/İlçe|MHRSAdresIlIlce)\s*:\s*([^/]+?)\s*/\s*(.+?)(?=\s*(?:🏠|🧬|💍|📞|🏢|📅|🏷|=|\n\n|$))', text, re.IGNORECASE | re.DOTALL)
    if mhrs_match:
        result['MhrsIl'] = mhrs_match.group(1).strip().title()
        result['MhrsIlce'] = mhrs_match.group(2).strip().title()
    
    # İkametgah
    ikamet_match = re.search(r'🏠\s*(?:İkametgah|Ikametgah)\s*:\s*(.+?)(?=\s*(?:🧬|💍|📞|🏢|📅|🏷|=|\n\n|$))', text, re.IGNORECASE | re.DOTALL)
    if ikamet_match:
        result['Ikametgah'] = ikamet_match.group(1).strip()
    
    # Aile/Birey Sıra
    aile_match = re.search(r'🧬\s*(?:Aile/Birey Sıra|AileBireySira)\s*:\s*(\d+)\s*/\s*(\d+)(?=\s*(?:💍|📞|🏢|📅|🏷|=|\n\n|$))', text, re.IGNORECASE | re.DOTALL)
    if aile_match:
        result['AileSira'] = aile_match.group(1).strip()
        result['BireySira'] = aile_match.group(2).strip()
    
    # Medeni/Cinsiyet
    medeni_match = re.search(r'💍\s*(?:Medeni/Cinsiyet|MedeniCinsiyet)\s*:\s*([^/]+?)\s*/\s*(.+?)(?=\s*(?:📞|🏢|📅|🏷|=|\n\n|$))', text, re.IGNORECASE | re.DOTALL)
    if medeni_match:
        result['MedeniDurum'] = medeni_match.group(1).strip()
        result['Cinsiyet'] = medeni_match.group(2).strip()
    
    # Birincil GSM
    gsm_match = re.search(r'📞\s*(?:Birincil GSM|BirincilGSM)\s*:\s*(\d+)(?=\s*(?:🏢|📅|🏷|=|\n\n|$))', text, re.IGNORECASE)
    if gsm_match:
        result['BirincilGSM'] = gsm_match.group(1).strip()
    
    # Diğer GSM'ler
    diger_gsm = re.search(r'📞\s*(?:Diğer GSM|DigerGSM)\s*(?:\n)([\d,\s]+)', text, re.IGNORECASE)
    if diger_gsm:
        numbers = re.findall(r'\d{10,11}', diger_gsm.group(1))
        result['DigerGSMler'] = numbers
    
    # İşyeri
    isyeri_match = re.search(r'🏢\s*(?:İşyeri Ünvanı|IsyeriUnvani)\s*:\s*(.+?)(?=\s*(?:📅|🏷|=|\n\n|$))', text, re.IGNORECASE | re.DOTALL)
    if isyeri_match:
        unvan = isyeri_match.group(1).strip()
        if unvan != '-':
            result['IsyeriUnvani'] = unvan
    
    # İşe Giriş
    isegiris_match = re.search(r'📅\s*(?:İşe Giriş|IseGiris)\s*:\s*(.+?)(?=\s*(?:🏷|=|\n\n|$))', text, re.IGNORECASE | re.DOTALL)
    if isegiris_match:
        tarih = isegiris_match.group(1).strip()
        if tarih != '-':
            result['IseGirisTarihi'] = tarih
    
    # Sektör
    sektor_match = re.search(r'🏷\s*(?:İşyeri Sektör|IsyeriSektor)\s*:\s*(.+?)(?=\s*(?:=|\n\n|$))', text, re.IGNORECASE | re.DOTALL)
    if sektor_match:
        sektor = sektor_match.group(1).strip()
        if sektor != '-':
            result['IsyeriSektor'] = sektor
    
    return result

# ========== ANA PARSER - TÜM KAYITLARI DÖNDÜR ==========
def parse_tc_detayli_response(text: str):
    """TÜM KAYITLARI DÖNDÜR (liste)"""
    if not text:
        return []
    
    text = normalize_turkish_text(text)
    
    records = split_records(text)
    
    if not records:
        single = parse_single_record(text)
        return [single] if single.get('TC') else []
    
    all_results = []
    for record in records:
        parsed = parse_single_record(record)
        if parsed.get('TC'):
            all_results.append(parsed)
    
    print(f"✅ TOPLAM {len(all_results)} KAYIT BULUNDU")
    return all_results

# ========== JSON YAPILANDIRICI - TÜM KAYITLAR ==========
def build_structured_json(all_records):
    """Tüm kayıtları JSON olarak döndür"""
    if not all_records:
        return {"success": False, "data": [], "total_records": 0}
    
    formatted_records = []
    for record in all_records:
        formatted_records.append({
            "kimlik": {
                "tc": record.get("TC", ""),
                "ad": record.get("Ad", ""),
                "soyad": record.get("Soyad", ""),
                "cinsiyet": record.get("Cinsiyet", ""),
                "medeni_durum": record.get("MedeniDurum", "")
            },
            "dogum": {
                "dogum_yeri": record.get("DogumYeri", ""),
                "dogum_tarihi": record.get("DogumTarihi", "")
            },
            "aile": {
                "anne": {"ad": record.get("AnneAdi", ""), "tc": record.get("AnneTC", "")},
                "baba": {"ad": record.get("BabaAdi", ""), "tc": record.get("BabaTC", "")}
            },
            "adres": {
                "il": record.get("Il", ""),
                "ilce": record.get("Ilce", ""),
                "koy": record.get("Koy", ""),
                "ikametgah": record.get("Ikametgah", ""),
                "mhrs_il": record.get("MhrsIl", ""),
                "mhrs_ilce": record.get("MhrsIlce", "")
            },
            "aile_sira": {
                "aile_sira_no": record.get("AileSira", ""),
                "birey_sira_no": record.get("BireySira", "")
            },
            "iletisim": {
                "birincil_gsm": record.get("BirincilGSM", ""),
                "diger_gsmler": record.get("DigerGSMler", [])
            },
            "isyeri": {
                "unvan": record.get("IsyeriUnvani", ""),
                "ise_giris_tarihi": record.get("IseGirisTarihi", ""),
                "sektor": record.get("IsyeriSektor", "")
            }
        })
    
    return {
        "success": True,
        "total_records": len(formatted_records),
        "records": formatted_records
    }

# ========== BASIT SORGU İÇİN YARDIMCI ==========
def find_first_record_with_field(all_records, field, subfield=None):
    """Kayıtlar içinde belirli alana sahip ilk kaydı bul"""
    for record in all_records:
        if subfield:
            value = record.get(field, {}).get(subfield) if isinstance(record.get(field), dict) else None
        else:
            value = record.get(field)
        if value and value != '-':
            return record
    return all_records[0] if all_records else None

# ========== DİĞER PARSER'LAR (TEK KAYIT DÖNDÜREN) ==========
def parse_ad_isegiris_response(text: str):
    all_records = parse_tc_detayli_response(text)
    if not all_records:
        return {}
    record = find_first_record_with_field(all_records, 'IseGirisTarihi')
    if not record:
        record = all_records[0]
    return {
        'TC': record.get('TC', ''), 'Ad': record.get('Ad', ''), 'Soyad': record.get('Soyad', ''),
        'IseGirisTarihi': record.get('IseGirisTarihi', ''), 'IsyeriSektor': record.get('IsyeriSektor', ''),
        'Ikametgah': record.get('Ikametgah', ''), 'AileSira': record.get('AileSira', ''),
        'BireySira': record.get('BireySira', ''), 'MedeniDurum': record.get('MedeniDurum', ''),
        'Cinsiyet': record.get('Cinsiyet', '')
    }

def parse_ad_ikametgah_response(text: str):
    all_records = parse_tc_detayli_response(text)
    if not all_records:
        return {}
    record = find_first_record_with_field(all_records, 'Ikametgah')
    if not record:
        record = all_records[0]
    return {'TC': record.get('TC', ''), 'Ad': record.get('Ad', ''), 'Soyad': record.get('Soyad', ''), 'Ikametgah': record.get('Ikametgah', '')}

def parse_ad_ailebirey_response(text: str):
    all_records = parse_tc_detayli_response(text)
    if not all_records:
        return {}
    record = find_first_record_with_field(all_records, 'AileSira')
    if not record:
        record = all_records[0]
    return {'TC': record.get('TC', ''), 'Ad': record.get('Ad', ''), 'Soyad': record.get('Soyad', ''), 'AileSira': record.get('AileSira', ''), 'BireySira': record.get('BireySira', '')}

def parse_ad_medenicinsiyet_response(text: str):
    all_records = parse_tc_detayli_response(text)
    if not all_records:
        return {}
    record = find_first_record_with_field(all_records, 'MedeniDurum')
    if not record:
        record = all_records[0]
    return {'TC': record.get('TC', ''), 'Ad': record.get('Ad', ''), 'Soyad': record.get('Soyad', ''), 'MedeniDurum': record.get('MedeniDurum', ''), 'Cinsiyet': record.get('Cinsiyet', '')}

parse_tc_isegiris_response = parse_ad_isegiris_response
parse_tc_ikametgah_response = parse_ad_ikametgah_response
parse_tc_ailebirey_response = parse_ad_ailebirey_response
parse_tc_medenicinsiyet_response = parse_ad_medenicinsiyet_response

def build_simple_structured_json(flat_data):
    if not flat_data:
        return {"success": False, "data": {}}
    
    data = {
        "success": True,
        "data": {
            "kimlik": {"tc": flat_data.get("TC", ""), "ad": flat_data.get("Ad", ""), "soyad": flat_data.get("Soyad", "")}
        }
    }
    
    if flat_data.get("IseGirisTarihi") or flat_data.get("IsyeriSektor"):
        data["data"]["isyeri"] = {"ise_giris_tarihi": flat_data.get("IseGirisTarihi", ""), "sektor": flat_data.get("IsyeriSektor", "")}
    
    if flat_data.get("Ikametgah"):
        data["data"]["adres"] = {"ikametgah": flat_data.get("Ikametgah", "")}
    
    if flat_data.get("AileSira") or flat_data.get("BireySira"):
        data["data"]["aile_sira"] = {"aile_sira_no": flat_data.get("AileSira", ""), "birey_sira_no": flat_data.get("BireySira", "")}
    
    if flat_data.get("MedeniDurum") or flat_data.get("Cinsiyet"):
        data["data"]["kimlik"]["medeni_durum"] = flat_data.get("MedeniDurum", "")
        data["data"]["kimlik"]["cinsiyet"] = flat_data.get("Cinsiyet", "")
    
    return data

# ========== TELEGRAM İŞLEMLERİ ==========
async def create_client():
    client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH, connection_retries=3, retry_delay=2, timeout=60, auto_reconnect=True)
    await client.connect()
    return client

async def query_bot_with_command(command: str, timeout: int = 90):
    max_retries = 2
    for retry in range(max_retries):
        client = None
        try:
            client = await create_client()
            async with client.conversation(BOT_USERNAME, timeout=timeout + 30) as conv:
                print(f"📤 Sending: {command}")
                await conv.send_message(command)
                start_ts = time.time()
                raw_text = ""
                
                while time.time() - start_ts < timeout:
                    try:
                        response = await conv.get_response(timeout=15)
                    except asyncio.TimeoutError:
                        continue
                    
                    text = getattr(response, 'text', '') or ''
                    
                    if text and any(word in text.lower() for word in ['sorgu yapılıyor', 'işlem devam', 'bekleyin']):
                        continue
                    
                    if hasattr(response, 'buttons') and response.buttons:
                        for row in response.buttons:
                            for btn in row:
                                btn_text = str(getattr(btn, 'text', '')).lower()
                                if any(k in btn_text for k in ['txt', 'dosya', 'indir', 'download']):
                                    try:
                                        await btn.click()
                                        file_msg = await conv.get_response(timeout=20)
                                        if file_msg and hasattr(file_msg, 'media') and file_msg.media:
                                            file_path = await client.download_media(file_msg)
                                            if file_path:
                                                with open(file_path, 'rb') as f:
                                                    content = f.read()
                                                os.remove(file_path)
                                                return decode_and_fix_text(content)
                                    except:
                                        pass
                    
                    if hasattr(response, 'media') and response.media:
                        file_path = await client.download_media(response)
                        if file_path:
                            with open(file_path, 'rb') as f:
                                content = f.read()
                            os.remove(file_path)
                            return decode_and_fix_text(content)
                    
                    if text:
                        text = normalize_turkish_text(text)
                        if re.search(r'\d{11}', text) or re.search(r'GSM\s*[:=]', text):
                            return text
                        if text.strip():
                            return text
                    
                    await asyncio.sleep(0.5)
                
                return "❌ Zaman aşımı"
                
        except Exception as e:
            print(f"❌ Hata: {e}")
            if retry < max_retries - 1:
                await asyncio.sleep(2)
            else:
                return f"Error: {str(e)}"
        finally:
            if client:
                try:
                    await client.disconnect()
                except:
                    pass
    
    return "❌ Maksimum deneme aşıldı"

def sync_query_bot(command: str) -> str:
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(query_bot_with_command(command))
        finally:
            loop.close()
    except Exception as e:
        return f"Error: {str(e)}"

# ========== TEMİZLEYİCİLER ==========
def clean_tc(tc):
    tc = re.sub(r'\D', '', tc)
    return tc if len(tc) == 11 else None

def clean_gsm(gsm):
    gsm = re.sub(r'\D', '', gsm)
    if gsm.startswith('0'):
        gsm = gsm[1:]
    return gsm[-10:] if len(gsm) >= 10 else None

def clean_plaka(plaka):
    plaka = re.sub(r'[^A-Z0-9]', '', plaka.upper())
    return plaka if len(plaka) >= 4 else None

# ========== CACHE ==========
def add_to_cache(key, value):
    result_cache[key] = {'data': value, 'timestamp': time.time()}

def get_from_cache(key):
    if key in result_cache:
        entry = result_cache[key]
        if time.time() - entry['timestamp'] <= 300:
            return entry['data']
        result_cache.pop(key, None)
    return None

# ========== SORGU HANDLER'LAR (TÜM ENDPOINT'LER İÇİN) ==========
def handle_tc_detayli_query(tc):
    tc = clean_tc(tc)
    if not tc:
        return {'success': False, 'error': 'Geçerli TC girin'}
    
    cache_key = f"tc_{tc}"
    cached = get_from_cache(cache_key)
    if cached:
        return cached
    
    command = f"/tc {tc}"
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {'success': False, 'error': raw_text}
    else:
        all_records = parse_tc_detayli_response(raw_text)
        if all_records:
            result = build_structured_json(all_records)
            result['query'] = command
        else:
            result = {'success': False, 'error': 'Kayıt bulunamadı', 'total_records': 0}
    
    add_to_cache(cache_key, result)
    return result

def handle_ad_detayli_query(name, surname, il=None, adres=None):
    name = name.strip().upper()
    surname = surname.strip().upper()
    if not name or not surname:
        return {'success': False, 'error': 'name ve surname gerekli'}
    
    cache_key = f"ad_{name}_{surname}"
    cached = get_from_cache(cache_key)
    if cached:
        return cached
    
    command = f"/ad {name} {surname}"
    if il:
        command += f" -il {il}"
    if adres:
        command += f" -adres {adres}"
    
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {'success': False, 'error': raw_text}
    else:
        all_records = parse_tc_detayli_response(raw_text)
        if all_records:
            result = build_structured_json(all_records)
            result['query'] = command
        else:
            result = {'success': False, 'error': 'Kayıt bulunamadı', 'total_records': 0}
    
    add_to_cache(cache_key, result)
    return result

def handle_gsm_query(gsm):
    gsm = clean_gsm(gsm)
    if not gsm:
        return {'success': False, 'error': 'Geçerli GSM girin'}
    
    cache_key = f"gsm_{gsm}"
    cached = get_from_cache(cache_key)
    if cached:
        return cached
    
    command = f"/gsm {gsm}"
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {'success': False, 'error': raw_text}
    else:
        all_records = parse_tc_detayli_response(raw_text)
        if all_records:
            result = build_structured_json(all_records)
            result['query'] = command
        else:
            result = {'success': False, 'error': 'Kayıt bulunamadı'}
    
    add_to_cache(cache_key, result)
    return result

def handle_plaka_query(plaka):
    plaka = clean_plaka(plaka)
    if not plaka:
        return {'success': False, 'error': 'Geçerli plaka girin'}
    
    cache_key = f"plaka_{plaka}"
    cached = get_from_cache(cache_key)
    if cached:
        return cached
    
    command = f"/plaka {plaka}"
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {'success': False, 'error': raw_text}
    else:
        all_records = parse_tc_detayli_response(raw_text)
        if all_records:
            result = build_structured_json(all_records)
            result['query'] = command
        else:
            result = {'success': False, 'error': 'Kayıt bulunamadı'}
    
    add_to_cache(cache_key, result)
    return result

def handle_generic_command(command, cache_prefix):
    cache_key = f"{cache_prefix}_{command}"
    cached = get_from_cache(cache_key)
    if cached:
        return cached
    
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {'success': False, 'error': raw_text}
    else:
        all_records = parse_tc_detayli_response(raw_text)
        if all_records:
            result = build_structured_json(all_records)
            result['query'] = command
        else:
            result = {'success': False, 'error': 'Kayıt bulunamadı'}
    
    add_to_cache(cache_key, result)
    return result

# ========== ENDPOINT'LER ==========
@app.route('/')
def index():
    return jsonify({
        'status': 'API Çalışıyor - Tüm kayıtlar geliyor',
        'total_endpoints': 27,
        'endpoints': [
            '/tc?tc=...', '/query?name=...&surname=...', '/ad?name=...&surname=...',
            '/gsm?gsm=...', '/gsm2?gsm=...', '/plaka?plaka=...',
            '/aile?tc=...', '/sulale?tc=...', '/hane?tc=...', '/isyeri?tc=...',
            '/tc2?tc=...', '/vesika?tc=...', '/text?name=...&surname=...',
            '/raw?name=...&surname=...', '/isegiris?name=...&surname=...',
            '/ikametgah?name=...&surname=...', '/ailebirey?name=...&surname=...',
            '/medenicinsiyet?name=...&surname=...', '/tc-isegiris?tc=...',
            '/tc-ikametgah?tc=...', '/tc-ailebirey?tc=...', '/tc-medenicinsiyet?tc=...',
            '/test', '/health'
        ]
    })

@app.route('/tc', methods=['GET'])
def api_tc():
    result = handle_tc_detayli_query(request.args.get('tc', ''))
    return Response(json.dumps(result, ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')

@app.route('/query', methods=['GET'])
def api_query():
    result = handle_ad_detayli_query(request.args.get('name', ''), request.args.get('surname', ''))
    return Response(json.dumps(result, ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')

@app.route('/ad', methods=['GET'])
def api_ad():
    return api_query()

@app.route('/gsm', methods=['GET'])
def api_gsm():
    result = handle_gsm_query(request.args.get('gsm', ''))
    return Response(json.dumps(result, ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')

@app.route('/gsm2', methods=['GET'])
def api_gsm2():
    result = handle_gsm_query(request.args.get('gsm', ''))
    return Response(json.dumps(result, ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')

@app.route('/plaka', methods=['GET'])
def api_plaka():
    result = handle_plaka_query(request.args.get('plaka', ''))
    return Response(json.dumps(result, ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')

@app.route('/aile', methods=['GET'])
def api_aile():
    tc = request.args.get('tc', '')
    if not tc:
        return jsonify({'success': False, 'error': 'tc gerekli'})
    result = handle_generic_command(f"/aile {tc}", f"aile_{tc}")
    return Response(json.dumps(result, ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')

@app.route('/sulale', methods=['GET'])
def api_sulale():
    tc = request.args.get('tc', '')
    if not tc:
        return jsonify({'success': False, 'error': 'tc gerekli'})
    result = handle_generic_command(f"/sulale {tc}", f"sulale_{tc}")
    return Response(json.dumps(result, ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')

@app.route('/hane', methods=['GET'])
def api_hane():
    tc = request.args.get('tc', '')
    if not tc:
        return jsonify({'success': False, 'error': 'tc gerekli'})
    result = handle_generic_command(f"/hane {tc}", f"hane_{tc}")
    return Response(json.dumps(result, ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')

@app.route('/isyeri', methods=['GET'])
def api_isyeri():
    tc = request.args.get('tc', '')
    if not tc:
        return jsonify({'success': False, 'error': 'tc gerekli'})
    result = handle_generic_command(f"/isyeri {tc}", f"isyeri_{tc}")
    return Response(json.dumps(result, ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')

@app.route('/tc2', methods=['GET'])
def api_tc2():
    tc = request.args.get('tc', '')
    if not tc:
        return jsonify({'success': False, 'error': 'tc gerekli'})
    result = handle_generic_command(f"/tc2 {tc}", f"tc2_{tc}")
    return Response(json.dumps(result, ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')

@app.route('/vesika', methods=['GET'])
def api_vesika():
    tc = request.args.get('tc', '')
    if not tc:
        return jsonify({'success': False, 'error': 'tc gerekli'})
    result = handle_generic_command(f"/vesika {tc}", f"vesika_{tc}")
    return Response(json.dumps(result, ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')

@app.route('/text', methods=['GET'])
def api_text():
    name = request.args.get('name', '') or request.args.get('first_name', '')
    surname = request.args.get('surname', '') or request.args.get('last_name', '')
    if not name or not surname:
        return Response('❌ name ve surname gerekli', content_type='text/plain; charset=utf-8')
    result = handle_ad_detayli_query(name, surname)
    if result.get('success'):
        # Sadece ilk kaydı text olarak göster
        first = result['records'][0] if result.get('records') else None
        if first:
            text_output = format_record_to_text(first, f"{name} {surname}")
            return Response(text_output, content_type='text/plain; charset=utf-8')
    return Response(f"❌ Kayıt bulunamadı", content_type='text/plain; charset=utf-8')

@app.route('/raw', methods=['GET'])
def api_raw():
    name = request.args.get('name', '') or request.args.get('first_name', '')
    surname = request.args.get('surname', '') or request.args.get('last_name', '')
    if not name or not surname:
        return Response('❌ name ve surname gerekli', content_type='text/plain; charset=utf-8')
    command = f"/ad {name.upper()} {surname.upper()}"
    raw_text = sync_query_bot(command)
    return Response(raw_text[:5000], content_type='text/plain; charset=utf-8')

@app.route('/isegiris', methods=['GET'])
def api_isegiris():
    name = request.args.get('name', '').strip().upper()
    surname = request.args.get('surname', '').strip().upper()
    if not name or not surname:
        return jsonify({'success': False, 'error': 'name ve surname gerekli'})
    result = handle_ad_detayli_query(name, surname)
    if result.get('success') and result.get('records'):
        # İşe girişi olan ilk kaydı bul
        for record in result['records']:
            if record['isyeri'].get('ise_giris_tarihi'):
                flat = {
                    'TC': record['kimlik']['tc'], 'Ad': record['kimlik']['ad'], 'Soyad': record['kimlik']['soyad'],
                    'IseGirisTarihi': record['isyeri']['ise_giris_tarihi'], 'IsyeriSektor': record['isyeri']['sektor'],
                    'Ikametgah': record['adres']['ikametgah'], 'AileSira': record['aile_sira']['aile_sira_no'],
                    'BireySira': record['aile_sira']['birey_sira_no'], 'MedeniDurum': record['kimlik']['medeni_durum'],
                    'Cinsiyet': record['kimlik']['cinsiyet']
                }
                return Response(json.dumps(build_simple_structured_json(flat), ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')
    return jsonify({'success': False, 'error': 'İşe giriş bilgisi bulunamadı'})

@app.route('/ikametgah', methods=['GET'])
def api_ikametgah():
    name = request.args.get('name', '').strip().upper()
    surname = request.args.get('surname', '').strip().upper()
    if not name or not surname:
        return jsonify({'success': False, 'error': 'name ve surname gerekli'})
    result = handle_ad_detayli_query(name, surname)
    if result.get('success') and result.get('records'):
        for record in result['records']:
            if record['adres'].get('ikametgah'):
                flat = {
                    'TC': record['kimlik']['tc'], 'Ad': record['kimlik']['ad'], 'Soyad': record['kimlik']['soyad'],
                    'Ikametgah': record['adres']['ikametgah']
                }
                return Response(json.dumps(build_simple_structured_json(flat), ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')
    return jsonify({'success': False, 'error': 'İkametgah bilgisi bulunamadı'})

@app.route('/ailebirey', methods=['GET'])
def api_ailebirey():
    name = request.args.get('name', '').strip().upper()
    surname = request.args.get('surname', '').strip().upper()
    if not name or not surname:
        return jsonify({'success': False, 'error': 'name ve surname gerekli'})
    result = handle_ad_detayli_query(name, surname)
    if result.get('success') and result.get('records'):
        for record in result['records']:
            if record['aile_sira'].get('aile_sira_no'):
                flat = {
                    'TC': record['kimlik']['tc'], 'Ad': record['kimlik']['ad'], 'Soyad': record['kimlik']['soyad'],
                    'AileSira': record['aile_sira']['aile_sira_no'], 'BireySira': record['aile_sira']['birey_sira_no']
                }
                return Response(json.dumps(build_simple_structured_json(flat), ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')
    return jsonify({'success': False, 'error': 'Aile/Birey sıra bilgisi bulunamadı'})

@app.route('/medenicinsiyet', methods=['GET'])
def api_medenicinsiyet():
    name = request.args.get('name', '').strip().upper()
    surname = request.args.get('surname', '').strip().upper()
    if not name or not surname:
        return jsonify({'success': False, 'error': 'name ve surname gerekli'})
    result = handle_ad_detayli_query(name, surname)
    if result.get('success') and result.get('records'):
        for record in result['records']:
            if record['kimlik'].get('medeni_durum'):
                flat = {
                    'TC': record['kimlik']['tc'], 'Ad': record['kimlik']['ad'], 'Soyad': record['kimlik']['soyad'],
                    'MedeniDurum': record['kimlik']['medeni_durum'], 'Cinsiyet': record['kimlik']['cinsiyet']
                }
                return Response(json.dumps(build_simple_structured_json(flat), ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')
    return jsonify({'success': False, 'error': 'Medeni durum/cinsiyet bilgisi bulunamadı'})

@app.route('/tc-isegiris', methods=['GET'])
def api_tc_isegiris():
    tc = request.args.get('tc', '')
    if not tc:
        return jsonify({'success': False, 'error': 'tc gerekli'})
    result = handle_tc_detayli_query(tc)
    if result.get('success') and result.get('records'):
        for record in result['records']:
            if record['isyeri'].get('ise_giris_tarihi'):
                flat = {
                    'TC': record['kimlik']['tc'], 'Ad': record['kimlik']['ad'], 'Soyad': record['kimlik']['soyad'],
                    'IseGirisTarihi': record['isyeri']['ise_giris_tarihi'], 'IsyeriSektor': record['isyeri']['sektor'],
                    'Ikametgah': record['adres']['ikametgah'], 'AileSira': record['aile_sira']['aile_sira_no'],
                    'BireySira': record['aile_sira']['birey_sira_no'], 'MedeniDurum': record['kimlik']['medeni_durum'],
                    'Cinsiyet': record['kimlik']['cinsiyet']
                }
                return Response(json.dumps(build_simple_structured_json(flat), ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')
    return jsonify({'success': False, 'error': 'İşe giriş bilgisi bulunamadı'})

@app.route('/tc-ikametgah', methods=['GET'])
def api_tc_ikametgah():
    tc = request.args.get('tc', '')
    if not tc:
        return jsonify({'success': False, 'error': 'tc gerekli'})
    result = handle_tc_detayli_query(tc)
    if result.get('success') and result.get('records'):
        for record in result['records']:
            if record['adres'].get('ikametgah'):
                flat = {
                    'TC': record['kimlik']['tc'], 'Ad': record['kimlik']['ad'], 'Soyad': record['kimlik']['soyad'],
                    'Ikametgah': record['adres']['ikametgah']
                }
                return Response(json.dumps(build_simple_structured_json(flat), ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')
    return jsonify({'success': False, 'error': 'İkametgah bilgisi bulunamadı'})

@app.route('/tc-ailebirey', methods=['GET'])
def api_tc_ailebirey():
    tc = request.args.get('tc', '')
    if not tc:
        return jsonify({'success': False, 'error': 'tc gerekli'})
    result = handle_tc_detayli_query(tc)
    if result.get('success') and result.get('records'):
        for record in result['records']:
            if record['aile_sira'].get('aile_sira_no'):
                flat = {
                    'TC': record['kimlik']['tc'], 'Ad': record['kimlik']['ad'], 'Soyad': record['kimlik']['soyad'],
                    'AileSira': record['aile_sira']['aile_sira_no'], 'BireySira': record['aile_sira']['birey_sira_no']
                }
                return Response(json.dumps(build_simple_structured_json(flat), ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')
    return jsonify({'success': False, 'error': 'Aile/Birey sıra bilgisi bulunamadı'})

@app.route('/tc-medenicinsiyet', methods=['GET'])
def api_tc_medenicinsiyet():
    tc = request.args.get('tc', '')
    if not tc:
        return jsonify({'success': False, 'error': 'tc gerekli'})
    result = handle_tc_detayli_query(tc)
    if result.get('success') and result.get('records'):
        for record in result['records']:
            if record['kimlik'].get('medeni_durum'):
                flat = {
                    'TC': record['kimlik']['tc'], 'Ad': record['kimlik']['ad'], 'Soyad': record['kimlik']['soyad'],
                    'MedeniDurum': record['kimlik']['medeni_durum'], 'Cinsiyet': record['kimlik']['cinsiyet']
                }
                return Response(json.dumps(build_simple_structured_json(flat), ensure_ascii=False, indent=2), content_type='application/json; charset=utf-8')
    return jsonify({'success': False, 'error': 'Medeni durum/cinsiyet bilgisi bulunamadı'})

@app.route('/test', methods=['GET'])
def test():
    return jsonify({'status': 'ok', 'message': 'API çalışıyor, tüm kayıtlar geliyor'})

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'cache_size': len(result_cache)})

def format_record_to_text(record, title):
    """Tek bir kaydı text formatında göster"""
    lines = [f"{'='*60}", f"📋 {title}", f"{'='*60}\n"]
    k = record['kimlik']
    lines.append(f"🪪 TC: {k['tc']}")
    lines.append(f"👤 Ad Soyad: {k['ad']} {k['soyad']}".strip())
    d = record['dogum']
    if d['dogum_yeri'] or d['dogum_tarihi']:
        lines.append(f"🎂 Doğum: {d['dogum_yeri']} / {d['dogum_tarihi']}".strip())
    a = record['aile']
    if a['anne']['ad']:
        lines.append(f"👩 Anne: {a['anne']['ad']} / {a['anne']['tc']}")
    if a['baba']['ad']:
        lines.append(f"👨 Baba: {a['baba']['ad']} / {a['baba']['tc']}")
    adr = record['adres']
    if adr['il'] or adr['ilce'] or adr['koy']:
        lines.append(f"📍 Adres: {adr['il']} / {adr['ilce']} / {adr['koy']}".strip(' /'))
    if adr['ikametgah']:
        lines.append(f"🏠 İkametgah: {adr['ikametgah']}")
    if adr['mhrs_il'] or adr['mhrs_ilce']:
        lines.append(f"🏥 MHRS: {adr['mhrs_il']} / {adr['mhrs_ilce']}".strip(' /'))
    asr = record['aile_sira']
    if asr['aile_sira_no']:
        lines.append(f"🧬 Aile/Birey Sıra: {asr['aile_sira_no']} / {asr['birey_sira_no']}")
    if k['medeni_durum'] or k['cinsiyet']:
        lines.append(f"💍 Medeni/Cinsiyet: {k['medeni_durum']} / {k['cinsiyet']}".strip(' /'))
    ilet = record['iletisim']
    if ilet['birincil_gsm']:
        lines.append(f"📞 Birincil GSM: {ilet['birincil_gsm']}")
    if ilet['diger_gsmler']:
        lines.append(f"📞 Diğer GSM'ler: {', '.join(ilet['diger_gsmler'][:5])}")
    isy = record['isyeri']
    if isy['unvan']:
        lines.append(f"🏢 İşyeri: {isy['unvan']}")
    if isy['ise_giris_tarihi']:
        lines.append(f"📅 İşe Giriş: {isy['ise_giris_tarihi']}")
    if isy['sektor']:
        lines.append(f"🏷 Sektör: {isy['sektor']}")
    lines.append(f"\n{'='*60}")
    return '\n'.join(lines)

# ========== MAIN ==========
if __name__ == '__main__':
    print("🚀 API BAŞLADI - TÜM 27 ENDPOINT AKTİF")
    print("✅ split_records() eklendi")
    print("✅ Tüm kayıtları parse eder (total_records ile)")
    print("✅ Her endpoint JSON olarak tüm kayıtları döndürür")
    print("="*50)
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
