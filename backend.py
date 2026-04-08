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

# Render için port binding
PORT = int(os.environ.get('PORT', 5000))

# ========== GLOBALS ==========
result_cache = {}
app_started = False

# Her thread için ayrı event loop
thread_local = threading.local()

def get_event_loop():
    """Her thread için ayrı event loop oluştur"""
    if not hasattr(thread_local, 'loop'):
        thread_local.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(thread_local.loop)
    return thread_local.loop

# ========== IMPROVED UTILITIES ==========
def fix_unicode_escapes(text: str) -> str:
    """Unicode escape karakterlerini düzelt"""
    if not text:
        return ""
    try:
        if '\\u' in text:
            text = text.replace('\\\\u', '\\u')
            decoded = bytes(text, 'utf-8').decode('unicode_escape')
            return decoded
    except Exception as e:
        print(f"Unicode escape fix error: {e}")
    return text

def normalize_turkish_text(text: str) -> str:
    """Türkçe metni normalize et"""
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
        '\u00e4': 'ä', '\u00c4': 'Ä', '\u2018': "'", '\u2019': "'",
        '\u201c': '"', '\u201d': '"', '\u2013': '-', '\u2014': '-',
        '\u2026': '...', '\u00a0': ' ', '\u200b': '', '\u200e': '',
        '\u200f': '', '\u202a': '', '\u202c': '', '\ufeff': '',
    }
    
    result = text
    for wrong, correct in turkish_mapping.items():
        result = result.replace(wrong, correct)
    
    result = re.sub(r'\s+', ' ', result)
    return result.strip()

def decode_and_fix_text(content: bytes) -> str:
    """Bytes'ı decode et ve Türkçe karakterleri düzelt"""
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

# ========== GÜNCELLENMİŞ PARSER'LAR (EMOJİ BAZLI, SAĞLAM) ==========

def parse_tc_detayli_response(text: str):
    """TC detaylı sorgu sonucunu parse et - emoji bazlı, sağlam regex ile"""
    if not text:
        return {}
    
    text = normalize_turkish_text(text)
    
    result = {
        'TC': '',
        'Ad': '',
        'Soyad': '',
        'DogumYeri': '',
        'DogumTarihi': '',
        'AnneAdi': '',
        'AnneTC': '',
        'BabaAdi': '',
        'BabaTC': '',
        'Il': '',
        'Ilce': '',
        'Koy': '',
        'MhrsIl': '',
        'MhrsIlce': '',
        'Ikametgah': '',
        'AileSira': '',
        'BireySira': '',
        'MedeniDurum': '',
        'Cinsiyet': '',
        'BirincilGSM': '',
        'DigerGSMler': [],
        'IsyeriUnvani': '',
        'IseGirisTarihi': '',
        'IsyeriSektor': ''
    }
    
    # 🔥 GÜNCELLENDİ: TC - direkt rakam
    tc_match = re.search(r'🪪\s*TC\s*:\s*(\d{11})', text)
    if tc_match:
        result['TC'] = tc_match.group(1)
    
    # 🔥 GÜNCELLENDİ: Ad Soyad - bir sonraki emojiye kadar yakala
    ad_soyad_match = re.search(
        r'👤\s*(?:Adı Soyadı|Ad Soyad|AdSoyad)\s*:\s*(.*?)(?=\s*(?:🎂|👩|👨|📍|🏥|🏠|🧬|💍|📞|🏢|📅|🏷|$))',
        text,
        re.IGNORECASE | re.DOTALL
    )
    if ad_soyad_match:
        full_name = ad_soyad_match.group(1).strip().upper()
        # Temizlik
        full_name = re.sub(r'\s+', ' ', full_name)
        parts = full_name.split()
        if parts:
            result['Ad'] = parts[0]
            result['Soyad'] = " ".join(parts[1:]) if len(parts) > 1 else ""
    
    # 🔥 GÜNCELLENDİ: Doğum - bir sonraki emojiye kadar
    dogum_match = re.search(
        r'🎂\s*(?:Doğum|Dogum)[^(]*\(?(?:Yer/Tarih|YerTarih)\)?\s*:\s*([^/]+?)\s*/\s*([\d-]+?)(?=\s*(?:👩|👨|📍|🏥|🏠|🧬|💍|📞|🏢|📅|🏷|$))',
        text,
        re.IGNORECASE | re.DOTALL
    )
    if dogum_match:
        result['DogumYeri'] = dogum_match.group(1).strip().title()
        result['DogumTarihi'] = dogum_match.group(2).strip()
    
    # 🔥 GÜNCELLENDİ: Anne
    anne_match = re.search(
        r'👩\s*(?:Anne)[^(]*\(?(?:Ad/TC|AdTC)\)?\s*:\s*([^/]+?)\s*/\s*(\d{11})(?=\s*(?:👨|📍|🏥|🏠|🧬|💍|📞|🏢|📅|🏷|$))',
        text,
        re.IGNORECASE | re.DOTALL
    )
    if anne_match:
        result['AnneAdi'] = anne_match.group(1).strip().upper()
        result['AnneTC'] = anne_match.group(2).strip()
    
    # 🔥 GÜNCELLENDİ: Baba
    baba_match = re.search(
        r'👨\s*(?:Baba)[^(]*\(?(?:Ad/TC|AdTC)\)?\s*:\s*([^/]+?)\s*/\s*(\d{11})(?=\s*(?:📍|🏥|🏠|🧬|💍|📞|🏢|📅|🏷|$))',
        text,
        re.IGNORECASE | re.DOTALL
    )
    if baba_match:
        result['BabaAdi'] = baba_match.group(1).strip().upper()
        result['BabaTC'] = baba_match.group(2).strip()
    
    # 🔥 GÜNCELLENDİ: İl/İlçe/Köy
    yer_match = re.search(
        r'📍\s*(?:İl/İlçe/Köy|IlIlceKoy)\s*:\s*([^/]+?)\s*/\s*([^/]+?)\s*/\s*(.+?)(?=\s*(?:🏥|🏠|🧬|💍|📞|🏢|📅|🏷|$))',
        text,
        re.IGNORECASE | re.DOTALL
    )
    if yer_match:
        result['Il'] = yer_match.group(1).strip().title()
        result['Ilce'] = yer_match.group(2).strip().title()
        result['Koy'] = yer_match.group(3).strip().title()
    
    # 🔥 GÜNCELLENDİ: MHRS
    mhrs_match = re.search(
        r'🏥\s*(?:MHRS Adres İl/İlçe|MHRSAdresIlIlce)\s*:\s*([^/]+?)\s*/\s*(.+?)(?=\s*(?:🏠|🧬|💍|📞|🏢|📅|🏷|$))',
        text,
        re.IGNORECASE | re.DOTALL
    )
    if mhrs_match:
        result['MhrsIl'] = mhrs_match.group(1).strip().title()
        result['MhrsIlce'] = mhrs_match.group(2).strip().title()
    
    # 🔥 GÜNCELLENDİ: İkametgah
    ikamet_match = re.search(
        r'🏠\s*(?:İkametgah|Ikametgah)\s*:\s*(.+?)(?=\s*(?:🧬|💍|📞|🏢|📅|🏷|$))',
        text,
        re.IGNORECASE | re.DOTALL
    )
    if ikamet_match:
        result['Ikametgah'] = ikamet_match.group(1).strip()
    
    # 🔥 GÜNCELLENDİ: Aile/Birey Sıra
    aile_match = re.search(
        r'🧬\s*(?:Aile/Birey Sıra|AileBireySira)\s*:\s*(\d+)\s*/\s*(\d+)(?=\s*(?:💍|📞|🏢|📅|🏷|$))',
        text,
        re.IGNORECASE | re.DOTALL
    )
    if aile_match:
        result['AileSira'] = aile_match.group(1).strip()
        result['BireySira'] = aile_match.group(2).strip()
    
    # 🔥 GÜNCELLENDİ: Medeni/Cinsiyet
    medeni_match = re.search(
        r'💍\s*(?:Medeni/Cinsiyet|MedeniCinsiyet)\s*:\s*([^/]+?)\s*/\s*(.+?)(?=\s*(?:📞|🏢|📅|🏷|$))',
        text,
        re.IGNORECASE | re.DOTALL
    )
    if medeni_match:
        result['MedeniDurum'] = medeni_match.group(1).strip()
        result['Cinsiyet'] = medeni_match.group(2).strip()
    
    # 🔥 GÜNCELLENDİ: Birincil GSM
    gsm1_match = re.search(
        r'📞\s*(?:Birincil GSM|BirincilGSM)\s*:\s*(\d+)(?=\s*(?:🏢|📅|🏷|$))',
        text,
        re.IGNORECASE
    )
    if gsm1_match:
        result['BirincilGSM'] = gsm1_match.group(1).strip()
    
    # 🔥 GÜNCELLENDİ: Diğer GSM'ler
    diger_gsm_section = re.search(
        r'📞\s*(?:Diğer GSM|DigerGSM)\s*(?:\n)([\d,\s]+)',
        text,
        re.IGNORECASE
    )
    if diger_gsm_section:
        gsm_text = diger_gsm_section.group(1)
        numbers = re.findall(r'\d{10,11}', gsm_text)
        result['DigerGSMler'] = numbers
    
    # 🔥 GÜNCELLENDİ: İşyeri Ünvanı
    isyeri_match = re.search(
        r'🏢\s*(?:İşyeri Ünvanı|IsyeriUnvani)\s*:\s*(.+?)(?=\s*(?:📅|🏷|$))',
        text,
        re.IGNORECASE | re.DOTALL
    )
    if isyeri_match:
        unvan = isyeri_match.group(1).strip()
        if unvan != '-':
            result['IsyeriUnvani'] = unvan
    
    # 🔥 GÜNCELLENDİ: İşe Giriş Tarihi
    isegiris_match = re.search(
        r'📅\s*(?:İşe Giriş|IseGiris)\s*:\s*(.+?)(?=\s*(?:🏷|$))',
        text,
        re.IGNORECASE | re.DOTALL
    )
    if isegiris_match:
        tarih = isegiris_match.group(1).strip()
        if tarih != '-':
            result['IseGirisTarihi'] = tarih
    
    # 🔥 GÜNCELLENDİ: İşyeri Sektör
    sektor_match = re.search(
        r'🏷\s*(?:İşyeri Sektör|IsyeriSektor)\s*:\s*(.+?)(?=\s*$)',
        text,
        re.IGNORECASE | re.DOTALL
    )
    if sektor_match:
        sektor = sektor_match.group(1).strip()
        if sektor != '-':
            result['IsyeriSektor'] = sektor
    
    return result

def parse_ad_isegiris_response(text: str):
    """Ad soyad ile işe giriş sorgusundan sadece ilgili alanları çıkar"""
    if not text:
        return {}
    
    full_result = parse_tc_detayli_response(text)
    
    filtered_result = {
        'TC': full_result.get('TC', ''),
        'Ad': full_result.get('Ad', ''),
        'Soyad': full_result.get('Soyad', ''),
        'IseGirisTarihi': full_result.get('IseGirisTarihi', ''),
        'IsyeriSektor': full_result.get('IsyeriSektor', ''),
        'Ikametgah': full_result.get('Ikametgah', ''),
        'AileSira': full_result.get('AileSira', ''),
        'BireySira': full_result.get('BireySira', ''),
        'MedeniDurum': full_result.get('MedeniDurum', ''),
        'Cinsiyet': full_result.get('Cinsiyet', '')
    }
    
    return filtered_result

def parse_ad_ikametgah_response(text: str):
    """Ad soyad ile ikametgah sorgusundan sadece ikametgah bilgisini çıkar"""
    full_result = parse_tc_detayli_response(text)
    
    return {
        'TC': full_result.get('TC', ''),
        'Ad': full_result.get('Ad', ''),
        'Soyad': full_result.get('Soyad', ''),
        'Ikametgah': full_result.get('Ikametgah', '')
    }

def parse_ad_ailebirey_response(text: str):
    """Ad soyad ile aile/birey sıra sorgusundan sadece aile sıra bilgisini çıkar"""
    full_result = parse_tc_detayli_response(text)
    
    return {
        'TC': full_result.get('TC', ''),
        'Ad': full_result.get('Ad', ''),
        'Soyad': full_result.get('Soyad', ''),
        'AileSira': full_result.get('AileSira', ''),
        'BireySira': full_result.get('BireySira', '')
    }

def parse_ad_medenicinsiyet_response(text: str):
    """Ad soyad ile medeni durum/cinsiyet sorgusundan sadece o bilgileri çıkar"""
    full_result = parse_tc_detayli_response(text)
    
    return {
        'TC': full_result.get('TC', ''),
        'Ad': full_result.get('Ad', ''),
        'Soyad': full_result.get('Soyad', ''),
        'MedeniDurum': full_result.get('MedeniDurum', ''),
        'Cinsiyet': full_result.get('Cinsiyet', '')
    }

def parse_tc_isegiris_response(text: str):
    """TC ile işe giriş sorgusundan sadece ilgili alanları çıkar"""
    return parse_ad_isegiris_response(text)

def parse_tc_ikametgah_response(text: str):
    """TC ile ikametgah sorgusundan sadece ikametgah bilgisini çıkar"""
    return parse_ad_ikametgah_response(text)

def parse_tc_ailebirey_response(text: str):
    """TC ile aile/birey sıra sorgusundan sadece aile sıra bilgisini çıkar"""
    return parse_ad_ailebirey_response(text)

def parse_tc_medenicinsiyet_response(text: str):
    """TC ile medeni durum/cinsiyet sorgusundan sadece o bilgileri çıkar"""
    return parse_ad_medenicinsiyet_response(text)

# ========== JSON YAPILANDIRICI ==========

def build_structured_json(flat_data):
    """Düz JSON'u kategorili yapıya dönüştür"""
    if not flat_data:
        return {
            "success": False,
            "data": {}
        }
    
    return {
        "success": True,
        "data": {
            "kimlik": {
                "tc": flat_data.get("TC", ""),
                "ad": flat_data.get("Ad", ""),
                "soyad": flat_data.get("Soyad", ""),
                "cinsiyet": flat_data.get("Cinsiyet", ""),
                "medeni_durum": flat_data.get("MedeniDurum", "")
            },
            "dogum": {
                "dogum_yeri": flat_data.get("DogumYeri", ""),
                "dogum_tarihi": flat_data.get("DogumTarihi", "")
            },
            "aile": {
                "anne": {
                    "ad": flat_data.get("AnneAdi", ""),
                    "tc": flat_data.get("AnneTC", "")
                },
                "baba": {
                    "ad": flat_data.get("BabaAdi", ""),
                    "tc": flat_data.get("BabaTC", "")
                }
            },
            "adres": {
                "il": flat_data.get("Il", ""),
                "ilce": flat_data.get("Ilce", ""),
                "koy": flat_data.get("Koy", ""),
                "ikametgah": flat_data.get("Ikametgah", ""),
                "mhrs_il": flat_data.get("MhrsIl", ""),
                "mhrs_ilce": flat_data.get("MhrsIlce", "")
            },
            "aile_sira": {
                "aile_sira_no": flat_data.get("AileSira", ""),
                "birey_sira_no": flat_data.get("BireySira", "")
            },
            "iletisim": {
                "birincil_gsm": flat_data.get("BirincilGSM", ""),
                "diger_gsmler": flat_data.get("DigerGSMler", [])
            },
            "isyeri": {
                "unvan": flat_data.get("IsyeriUnvani", ""),
                "ise_giris_tarihi": flat_data.get("IseGirisTarihi", ""),
                "sektor": flat_data.get("IsyeriSektor", "")
            }
        }
    }

def build_simple_structured_json(flat_data):
    """Basit sorgular için (işe giriş, ikametgah vb.) JSON yapılandırıcı"""
    if not flat_data:
        return {
            "success": False,
            "data": {}
        }
    
    data = {
        "success": True,
        "data": {
            "kimlik": {
                "tc": flat_data.get("TC", ""),
                "ad": flat_data.get("Ad", ""),
                "soyad": flat_data.get("Soyad", "")
            }
        }
    }
    
    # İşe giriş bilgileri varsa ekle
    if flat_data.get("IseGirisTarihi") or flat_data.get("IsyeriSektor"):
        data["data"]["isyeri"] = {
            "ise_giris_tarihi": flat_data.get("IseGirisTarihi", ""),
            "sektor": flat_data.get("IsyeriSektor", "")
        }
    
    # İkametgah varsa ekle
    if flat_data.get("Ikametgah"):
        data["data"]["adres"] = {
            "ikametgah": flat_data.get("Ikametgah", "")
        }
    
    # Aile sıra varsa ekle
    if flat_data.get("AileSira") or flat_data.get("BireySira"):
        data["data"]["aile_sira"] = {
            "aile_sira_no": flat_data.get("AileSira", ""),
            "birey_sira_no": flat_data.get("BireySira", "")
        }
    
    # Medeni durum/cinsiyet varsa ekle
    if flat_data.get("MedeniDurum") or flat_data.get("Cinsiyet"):
        if "kimlik" not in data["data"]:
            data["data"]["kimlik"] = {}
        data["data"]["kimlik"]["medeni_durum"] = flat_data.get("MedeniDurum", "")
        data["data"]["kimlik"]["cinsiyet"] = flat_data.get("Cinsiyet", "")
    
    return data

# ========== TELEGRAM İŞLEMLERİ ==========
async def create_client():
    """Yeni bir Telegram client oluştur"""
    client = TelegramClient(
        StringSession(SESSION_STRING),
        int(API_ID),
        API_HASH,
        connection_retries=3,
        retry_delay=2,
        timeout=60,
        auto_reconnect=True
    )
    await client.connect()
    return client

async def query_bot_with_command(command: str, timeout: int = 90):
    """Bot'a komut gönder ve yanıt al"""
    max_retries = 2
    retry_delay = 2
    
    for retry in range(max_retries):
        client = None
        try:
            client = await create_client()
            
            async with client.conversation(BOT_USERNAME, timeout=timeout + 30) as conv:
                print(f"📤 Sending command: {command}")
                await conv.send_message(command)
                
                start_ts = time.time()
                raw_text = ""
                got_file = False
                
                while time.time() - start_ts < timeout:
                    try:
                        response = await conv.get_response(timeout=15)
                    except asyncio.TimeoutError:
                        print("⏳ Timeout waiting for response...")
                        continue
                    
                    text = getattr(response, 'text', '') or ''
                    
                    if text and any(word in text.lower() for word in ['sorgu yapılıyor', 'işlem devam', 'lütfen bekleyin', 'birazdan', 'yakında']):
                        print("⏳ Sorgu devam ediyor, bekleniyor...")
                        continue
                    
                    # Buton kontrolü
                    if hasattr(response, 'buttons') and response.buttons:
                        print("🔘 Buttons found, checking for download...")
                        for row in response.buttons:
                            for btn in row:
                                btn_text = str(getattr(btn, 'text', '')).lower()
                                if any(keyword in btn_text for keyword in ['txt', 'dosya', '.txt', 'indir', 'download', 'gör', 'aç']):
                                    print(f"📥 Found download button: {btn_text}")
                                    try:
                                        await btn.click()
                                        print("✅ Button clicked, waiting for file...")
                                        try:
                                            file_msg = await conv.get_response(timeout=20)
                                        except asyncio.TimeoutError:
                                            print("❌ Timeout waiting for file")
                                            continue
                                        
                                        if file_msg and hasattr(file_msg, 'media') and file_msg.media:
                                            print("📄 Downloading file...")
                                            file_path = await client.download_media(file_msg)
                                            if file_path and os.path.exists(file_path):
                                                try:
                                                    with open(file_path, 'rb') as f:
                                                        content = f.read()
                                                    
                                                    print(f"📊 File size: {len(content)} bytes")
                                                    raw_text = decode_and_fix_text(content)
                                                    got_file = True
                                                    print(f"✅ File downloaded and decoded, size: {len(raw_text)} chars")
                                                    
                                                finally:
                                                    try:
                                                        os.remove(file_path)
                                                    except:
                                                        pass
                                                
                                                if got_file:
                                                    return raw_text
                                    except Exception as e:
                                        print(f"❌ Button click error: {e}")
                                        continue
                    
                    # Direct media
                    if hasattr(response, 'media') and response.media:
                        print("📄 Message has media, downloading...")
                        try:
                            file_path = await client.download_media(response)
                            if file_path and os.path.exists(file_path):
                                with open(file_path, 'rb') as f:
                                    content = f.read()
                                
                                print(f"📊 Media file size: {len(content)} bytes")
                                raw_text = decode_and_fix_text(content)
                                
                                try:
                                    os.remove(file_path)
                                except:
                                    pass
                                
                                return raw_text
                        except Exception as e:
                            print(f"❌ Media download error: {e}")
                    
                    # Text data
                    if text:
                        text = normalize_turkish_text(text)
                        
                        if re.search(r'\d{11}', text) or re.search(r'GSM\s*[:=]\s*\d', text) or re.search(r'Plaka\s*[:=]', text, re.IGNORECASE):
                            raw_text = text
                            return raw_text
                        
                        if text.strip() and not any(word in text.lower() for word in ['sorgu yapılıyor', 'işlem devam']):
                            raw_text = text
                            return raw_text
                    
                    await asyncio.sleep(0.5)
                
                if raw_text:
                    return raw_text
                else:
                    return "❌ Sorgu zaman aşımına uğradı veya yanıt alınamadı"
                
        except Exception as e:
            print(f"❌ Query error (attempt {retry + 1}/{max_retries}): {e}")
            
            if retry < max_retries - 1:
                print(f"🔄 Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                return f"Error: {str(e)}"
        finally:
            if client:
                try:
                    await client.disconnect()
                except:
                    pass
    
    return "❌ Maximum retry attempts reached"

def sync_query_bot(command: str) -> str:
    """Async query'i sync context'te çalıştır"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(query_bot_with_command(command))
            return result
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()
            except:
                pass
            
    except Exception as e:
        print(f"❌ Sync query error: {e}")
        return f"Error: {str(e)}"

# ========== PARAMETRE TEMİZLEYİCİLER ==========
def clean_tc(tc):
    tc = re.sub(r'\D', '', tc)
    if len(tc) == 11:
        return tc
    return None

def clean_gsm(gsm):
    gsm = re.sub(r'\D', '', gsm)
    if gsm.startswith('0'):
        gsm = gsm[1:]
    if len(gsm) == 10:
        return gsm
    elif len(gsm) > 10:
        return gsm[-10:]
    return None

def clean_plaka(plaka):
    plaka = re.sub(r'[^A-Z0-9]', '', plaka.upper())
    if len(plaka) >= 4:
        return plaka
    return None

# ========== CACHE MANAGEMENT ==========
def add_to_cache(key, value):
    """Cache'e timestamp ile ekle"""
    result_cache[key] = {
        'data': value,
        'timestamp': time.time()
    }

def get_from_cache(key):
    """Cache'den timestamp kontrolü ile al"""
    if key in result_cache:
        cache_entry = result_cache[key]
        if isinstance(cache_entry, dict) and 'timestamp' in cache_entry:
            if time.time() - cache_entry['timestamp'] <= 300:  # 5 dakika
                return cache_entry['data']
            else:
                result_cache.pop(key, None)
    return None

def cleanup_cache():
    """Eski cache'leri temizle"""
    current_time = time.time()
    keys_to_remove = []
    
    for key, value in result_cache.items():
        if isinstance(value, dict) and 'timestamp' in value:
            if current_time - value['timestamp'] > 600:  # 10 dakika
                keys_to_remove.append(key)
    
    for key in keys_to_remove:
        result_cache.pop(key, None)
    
    if keys_to_remove:
        print(f"🧹 {len(keys_to_remove)} adet eski cache temizlendi")

# ========== TEXT FORMATTERS ==========
def format_isegiris_to_text(data, title="İşe Giriş Sorgu Sonucu"):
    """İşe giriş sorgu sonucunu text formatına dönüştür"""
    if not data:
        return "❌ Bilgi bulunamadı.\n"
    
    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"📋 {title}")
    lines.append(f"{'='*60}\n")
    
    if data.get('TC'):
        lines.append(f"🪪 TC: {data['TC']}")
    
    if data.get('Ad') or data.get('Soyad'):
        lines.append(f"👤 Ad Soyad: {data.get('Ad', '')} {data.get('Soyad', '')}".strip())
    
    if data.get('IseGirisTarihi'):
        lines.append(f"📅 İşe Giriş Tarihi: {data['IseGirisTarihi']}")
    
    if data.get('IsyeriSektor'):
        lines.append(f"🏷 İşyeri Sektör: {data['IsyeriSektor']}")
    
    if data.get('Ikametgah'):
        lines.append(f"🏠 İkametgah: {data['Ikametgah']}")
    
    if data.get('AileSira') and data.get('BireySira'):
        lines.append(f"🧬 Aile/Birey Sıra: {data['AileSira']} / {data['BireySira']}")
    
    if data.get('MedeniDurum') or data.get('Cinsiyet'):
        medeni_text = f"💍 Medeni Durum: {data.get('MedeniDurum', '')}"
        if data.get('Cinsiyet'):
            medeni_text += f" | Cinsiyet: {data['Cinsiyet']}"
        lines.append(medeni_text)
    
    lines.append(f"\n{'='*60}")
    
    return '\n'.join(lines)

def format_ikametgah_to_text(data, title="İkametgah Sorgu Sonucu"):
    """İkametgah sorgu sonucunu text formatına dönüştür"""
    if not data or not data.get('Ikametgah'):
        return "❌ İkametgah bilgisi bulunamadı.\n"
    
    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"📋 {title}")
    lines.append(f"{'='*60}\n")
    
    if data.get('TC'):
        lines.append(f"🪪 TC: {data['TC']}")
    
    if data.get('Ad') or data.get('Soyad'):
        lines.append(f"👤 Ad Soyad: {data.get('Ad', '')} {data.get('Soyad', '')}".strip())
    
    lines.append(f"🏠 İkametgah Adresi: {data['Ikametgah']}")
    
    lines.append(f"\n{'='*60}")
    
    return '\n'.join(lines)

def format_ailebirey_to_text(data, title="Aile/Birey Sıra Sorgu Sonucu"):
    """Aile/Birey sıra sorgu sonucunu text formatına dönüştür"""
    if not data or (not data.get('AileSira') and not data.get('BireySira')):
        return "❌ Aile/Birey sıra bilgisi bulunamadı.\n"
    
    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"📋 {title}")
    lines.append(f"{'='*60}\n")
    
    if data.get('TC'):
        lines.append(f"🪪 TC: {data['TC']}")
    
    if data.get('Ad') or data.get('Soyad'):
        lines.append(f"👤 Ad Soyad: {data.get('Ad', '')} {data.get('Soyad', '')}".strip())
    
    if data.get('AileSira'):
        lines.append(f"🧬 Aile Sıra No: {data['AileSira']}")
    
    if data.get('BireySira'):
        lines.append(f"👤 Birey Sıra No: {data['BireySira']}")
    
    lines.append(f"\n{'='*60}")
    
    return '\n'.join(lines)

def format_medenicinsiyet_to_text(data, title="Medeni Durum/Cinsiyet Sorgu Sonucu"):
    """Medeni durum/cinsiyet sorgu sonucunu text formatına dönüştür"""
    if not data or (not data.get('MedeniDurum') and not data.get('Cinsiyet')):
        return "❌ Medeni durum/cinsiyet bilgisi bulunamadı.\n"
    
    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"📋 {title}")
    lines.append(f"{'='*60}\n")
    
    if data.get('TC'):
        lines.append(f"🪪 TC: {data['TC']}")
    
    if data.get('Ad') or data.get('Soyad'):
        lines.append(f"👤 Ad Soyad: {data.get('Ad', '')} {data.get('Soyad', '')}".strip())
    
    if data.get('MedeniDurum'):
        lines.append(f"💍 Medeni Durum: {data['MedeniDurum']}")
    
    if data.get('Cinsiyet'):
        lines.append(f"⚥ Cinsiyet: {data['Cinsiyet']}")
    
    lines.append(f"\n{'='*60}")
    
    return '\n'.join(lines)

def format_tc_detayli_to_text(data, title="TC Sorgu Sonucu"):
    """TC detaylı sorgu sonucunu text formatına dönüştür"""
    if not data or not data.get('TC'):
        return "❌ Kayıt bulunamadı.\n"
    
    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"📋 {title}")
    lines.append(f"{'='*60}\n")
    
    lines.append(f"🪪 TC: {data.get('TC', '')}")
    
    if data.get('Ad') or data.get('Soyad'):
        lines.append(f"👤 Ad Soyad: {data.get('Ad', '')} {data.get('Soyad', '')}".strip())
    
    if data.get('DogumYeri') or data.get('DogumTarihi'):
        dogum_text = "🎂 Doğum: "
        if data.get('DogumYeri'):
            dogum_text += data['DogumYeri']
        if data.get('DogumTarihi'):
            if data.get('DogumYeri'):
                dogum_text += " / "
            dogum_text += data['DogumTarihi']
        lines.append(dogum_text)
    
    if data.get('AnneAdi') or data.get('AnneTC'):
        anne_text = f"👩 Anne: {data.get('AnneAdi', '')}"
        if data.get('AnneTC'):
            anne_text += f" / {data['AnneTC']}"
        lines.append(anne_text)
    
    if data.get('BabaAdi') or data.get('BabaTC'):
        baba_text = f"👨 Baba: {data.get('BabaAdi', '')}"
        if data.get('BabaTC'):
            baba_text += f" / {data['BabaTC']}"
        lines.append(baba_text)
    
    if data.get('Il') or data.get('Ilce') or data.get('Koy'):
        yer_text = "📍 Adres: "
        parts = []
        if data.get('Il'):
            parts.append(data['Il'])
        if data.get('Ilce'):
            parts.append(data['Ilce'])
        if data.get('Koy'):
            parts.append(data['Koy'])
        if parts:
            yer_text += " / ".join(parts)
            lines.append(yer_text)
    
    if data.get('MhrsIl') or data.get('MhrsIlce'):
        mhrs_text = "🏥 MHRS: "
        if data.get('MhrsIl'):
            mhrs_text += data['MhrsIl']
        if data.get('MhrsIlce'):
            if data.get('MhrsIl'):
                mhrs_text += " / "
            mhrs_text += data['MhrsIlce']
        lines.append(mhrs_text)
    
    if data.get('Ikametgah'):
        lines.append(f"🏠 İkametgah: {data['Ikametgah']}")
    
    if data.get('AileSira') and data.get('BireySira'):
        lines.append(f"🧬 Aile/Birey Sıra: {data['AileSira']} / {data['BireySira']}")
    
    if data.get('MedeniDurum') or data.get('Cinsiyet'):
        medeni_text = "💍 Medeni/Cinsiyet: "
        if data.get('MedeniDurum'):
            medeni_text += data['MedeniDurum']
        if data.get('Cinsiyet'):
            if data.get('MedeniDurum'):
                medeni_text += " / "
            medeni_text += data['Cinsiyet']
        lines.append(medeni_text)
    
    if data.get('BirincilGSM'):
        lines.append(f"📞 Birincil GSM: {data['BirincilGSM']}")
    
    if data.get('DigerGSMler'):
        lines.append(f"📞 Diğer GSM'ler: {', '.join(data['DigerGSMler'][:5])}")
        if len(data['DigerGSMler']) > 5:
            lines.append(f"   ... ve {len(data['DigerGSMler']) - 5} numara daha")
    
    if data.get('IsyeriUnvani'):
        lines.append(f"🏢 İşyeri: {data['IsyeriUnvani']}")
    
    if data.get('IseGirisTarihi'):
        lines.append(f"📅 İşe Giriş: {data['IseGirisTarihi']}")
    
    if data.get('IsyeriSektor'):
        lines.append(f"🏷 Sektör: {data['IsyeriSektor']}")
    
    lines.append(f"\n{'='*60}")
    
    return '\n'.join(lines)

# ========== APP INITIALIZATION ==========
def init_app():
    """Uygulama başlangıcında çalışır"""
    global app_started
    
    if not app_started:
        print("🎬 Initializing application...")
        app_started = True
        
        # Başlangıçta basit bir test yap
        try:
            test_command = "/ad TEST TEST"
            print(f"🔧 Running startup test: {test_command}")
            result = sync_query_bot(test_command)
            print(f"🔧 Startup test result length: {len(result)}")
            if "Error:" in result or "❌" in result:
                print(f"⚠️ Startup test warning: {result[:100]}")
            else:
                print("✅ Startup test completed successfully")
        except Exception as e:
            print(f"⚠️ Startup test error (non-critical): {e}")

# ========== SORGU HANDLER'LAR ==========

def handle_tc_detayli_query(tc):
    """TC ile detaylı sorgu yap"""
    tc = clean_tc(tc)
    if not tc:
        return {'success': False, 'error': 'Geçerli bir 11 haneli TC kimlik numarası giriniz'}
    
    cache_key = f"tc_detayli_{tc}"
    cached = get_from_cache(cache_key)
    if cached:
        print(f"📦 Cache hit for tc_detayli: {tc}")
        return cached
    
    command = f"/tc {tc}"
    print(f"🚀 Executing tc_detayli command: {command}")
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {
            'success': False,
            'query': command,
            'error': raw_text
        }
    else:
        data = parse_tc_detayli_response(raw_text)
        
        if data.get('TC'):
            # 🔥 GÜNCELLENDİ: build_structured_json kullan
            result = build_structured_json(data)
            result['query'] = command
        else:
            result = {
                'success': False,
                'query': command,
                'error': 'Kayıt bulunamadı',
                'data': data
            }
    
    add_to_cache(cache_key, result)
    return result

def handle_tc_isegiris_query(tc):
    """TC ile işe giriş sorgusu yap"""
    tc = clean_tc(tc)
    if not tc:
        return {'success': False, 'error': 'Geçerli bir 11 haneli TC kimlik numarası giriniz'}
    
    cache_key = f"tc_isegiris_{tc}"
    cached = get_from_cache(cache_key)
    if cached:
        print(f"📦 Cache hit for tc_isegiris: {tc}")
        return cached
    
    command = f"/tc {tc}"
    print(f"🚀 Executing tc_isegiris command: {command}")
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {
            'success': False,
            'query': command,
            'error': raw_text
        }
    else:
        data = parse_tc_isegiris_response(raw_text)
        
        if data.get('IseGirisTarihi') or data.get('IsyeriSektor'):
            # 🔥 GÜNCELLENDİ: build_simple_structured_json kullan
            result = build_simple_structured_json(data)
            result['query'] = command
        else:
            result = {
                'success': False,
                'query': command,
                'error': 'İşe giriş bilgisi bulunamadı',
                'data': data
            }
    
    add_to_cache(cache_key, result)
    return result

def handle_tc_ikametgah_query(tc):
    """TC ile ikametgah sorgusu yap"""
    tc = clean_tc(tc)
    if not tc:
        return {'success': False, 'error': 'Geçerli bir 11 haneli TC kimlik numarası giriniz'}
    
    cache_key = f"tc_ikametgah_{tc}"
    cached = get_from_cache(cache_key)
    if cached:
        print(f"📦 Cache hit for tc_ikametgah: {tc}")
        return cached
    
    command = f"/tc {tc}"
    print(f"🚀 Executing tc_ikametgah command: {command}")
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {
            'success': False,
            'query': command,
            'error': raw_text
        }
    else:
        data = parse_tc_ikametgah_response(raw_text)
        
        if data.get('Ikametgah'):
            # 🔥 GÜNCELLENDİ: build_simple_structured_json kullan
            result = build_simple_structured_json(data)
            result['query'] = command
        else:
            result = {
                'success': False,
                'query': command,
                'error': 'İkametgah bilgisi bulunamadı',
                'data': data
            }
    
    add_to_cache(cache_key, result)
    return result

def handle_tc_ailebirey_query(tc):
    """TC ile aile/birey sıra sorgusu yap"""
    tc = clean_tc(tc)
    if not tc:
        return {'success': False, 'error': 'Geçerli bir 11 haneli TC kimlik numarası giriniz'}
    
    cache_key = f"tc_ailebirey_{tc}"
    cached = get_from_cache(cache_key)
    if cached:
        print(f"📦 Cache hit for tc_ailebirey: {tc}")
        return cached
    
    command = f"/tc {tc}"
    print(f"🚀 Executing tc_ailebirey command: {command}")
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {
            'success': False,
            'query': command,
            'error': raw_text
        }
    else:
        data = parse_tc_ailebirey_response(raw_text)
        
        if data.get('AileSira') or data.get('BireySira'):
            # 🔥 GÜNCELLENDİ: build_simple_structured_json kullan
            result = build_simple_structured_json(data)
            result['query'] = command
        else:
            result = {
                'success': False,
                'query': command,
                'error': 'Aile/Birey sıra bilgisi bulunamadı',
                'data': data
            }
    
    add_to_cache(cache_key, result)
    return result

def handle_tc_medenicinsiyet_query(tc):
    """TC ile medeni durum/cinsiyet sorgusu yap"""
    tc = clean_tc(tc)
    if not tc:
        return {'success': False, 'error': 'Geçerli bir 11 haneli TC kimlik numarası giriniz'}
    
    cache_key = f"tc_medenicinsiyet_{tc}"
    cached = get_from_cache(cache_key)
    if cached:
        print(f"📦 Cache hit for tc_medenicinsiyet: {tc}")
        return cached
    
    command = f"/tc {tc}"
    print(f"🚀 Executing tc_medenicinsiyet command: {command}")
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {
            'success': False,
            'query': command,
            'error': raw_text
        }
    else:
        data = parse_tc_medenicinsiyet_response(raw_text)
        
        if data.get('MedeniDurum') or data.get('Cinsiyet'):
            # 🔥 GÜNCELLENDİ: build_simple_structured_json kullan
            result = build_simple_structured_json(data)
            result['query'] = command
        else:
            result = {
                'success': False,
                'query': command,
                'error': 'Medeni durum/cinsiyet bilgisi bulunamadı',
                'data': data
            }
    
    add_to_cache(cache_key, result)
    return result

def handle_ad_detayli_query(name, surname, il=None, adres=None):
    """Ad soyad ile detaylı sorgu yap"""
    name = name.strip().upper()
    surname = surname.strip().upper()
    
    if not name or not surname:
        return {'success': False, 'error': 'name ve surname gerekli'}
    
    cache_key = f"ad_detayli_{name}_{surname}_{il}_{adres}"
    cached = get_from_cache(cache_key)
    if cached:
        print(f"📦 Cache hit for ad_detayli: {name} {surname}")
        return cached
    
    command = f"/ad {name} {surname}"
    if il:
        command += f" -il {il}"
    if adres:
        command += f" -adres {adres}"
    
    print(f"🚀 Executing ad_detayli command: {command}")
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {
            'success': False,
            'query': command,
            'error': raw_text
        }
    else:
        data = parse_tc_detayli_response(raw_text)
        
        if data.get('TC'):
            # 🔥 GÜNCELLENDİ: build_structured_json kullan
            result = build_structured_json(data)
            result['query'] = command
        else:
            result = {
                'success': False,
                'query': command,
                'error': 'Kayıt bulunamadı',
                'data': data
            }
    
    add_to_cache(cache_key, result)
    return result

def handle_ad_isegiris_query(name, surname, il=None, adres=None):
    """Ad soyad ile işe giriş sorgusu yap"""
    name = name.strip().upper()
    surname = surname.strip().upper()
    
    if not name or not surname:
        return {'success': False, 'error': 'name ve surname gerekli'}
    
    cache_key = f"ad_isegiris_{name}_{surname}_{il}_{adres}"
    cached = get_from_cache(cache_key)
    if cached:
        print(f"📦 Cache hit for ad_isegiris: {name} {surname}")
        return cached
    
    command = f"/ad {name} {surname}"
    if il:
        command += f" -il {il}"
    if adres:
        command += f" -adres {adres}"
    
    print(f"🚀 Executing ad_isegiris command: {command}")
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {
            'success': False,
            'query': command,
            'error': raw_text
        }
    else:
        data = parse_ad_isegiris_response(raw_text)
        
        if data.get('IseGirisTarihi') or data.get('IsyeriSektor'):
            # 🔥 GÜNCELLENDİ: build_simple_structured_json kullan
            result = build_simple_structured_json(data)
            result['query'] = command
        else:
            result = {
                'success': False,
                'query': command,
                'error': 'İşe giriş bilgisi bulunamadı',
                'data': data
            }
    
    add_to_cache(cache_key, result)
    return result

def handle_ad_ikametgah_query(name, surname, il=None, adres=None):
    """Ad soyad ile ikametgah sorgusu yap"""
    name = name.strip().upper()
    surname = surname.strip().upper()
    
    if not name or not surname:
        return {'success': False, 'error': 'name ve surname gerekli'}
    
    cache_key = f"ad_ikametgah_{name}_{surname}_{il}_{adres}"
    cached = get_from_cache(cache_key)
    if cached:
        print(f"📦 Cache hit for ad_ikametgah: {name} {surname}")
        return cached
    
    command = f"/ad {name} {surname}"
    if il:
        command += f" -il {il}"
    if adres:
        command += f" -adres {adres}"
    
    print(f"🚀 Executing ad_ikametgah command: {command}")
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {
            'success': False,
            'query': command,
            'error': raw_text
        }
    else:
        data = parse_ad_ikametgah_response(raw_text)
        
        if data.get('Ikametgah'):
            # 🔥 GÜNCELLENDİ: build_simple_structured_json kullan
            result = build_simple_structured_json(data)
            result['query'] = command
        else:
            result = {
                'success': False,
                'query': command,
                'error': 'İkametgah bilgisi bulunamadı',
                'data': data
            }
    
    add_to_cache(cache_key, result)
    return result

def handle_ad_ailebirey_query(name, surname, il=None, adres=None):
    """Ad soyad ile aile/birey sıra sorgusu yap"""
    name = name.strip().upper()
    surname = surname.strip().upper()
    
    if not name or not surname:
        return {'success': False, 'error': 'name ve surname gerekli'}
    
    cache_key = f"ad_ailebirey_{name}_{surname}_{il}_{adres}"
    cached = get_from_cache(cache_key)
    if cached:
        print(f"📦 Cache hit for ad_ailebirey: {name} {surname}")
        return cached
    
    command = f"/ad {name} {surname}"
    if il:
        command += f" -il {il}"
    if adres:
        command += f" -adres {adres}"
    
    print(f"🚀 Executing ad_ailebirey command: {command}")
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {
            'success': False,
            'query': command,
            'error': raw_text
        }
    else:
        data = parse_ad_ailebirey_response(raw_text)
        
        if data.get('AileSira') or data.get('BireySira'):
            # 🔥 GÜNCELLENDİ: build_simple_structured_json kullan
            result = build_simple_structured_json(data)
            result['query'] = command
        else:
            result = {
                'success': False,
                'query': command,
                'error': 'Aile/Birey sıra bilgisi bulunamadı',
                'data': data
            }
    
    add_to_cache(cache_key, result)
    return result

def handle_ad_medenicinsiyet_query(name, surname, il=None, adres=None):
    """Ad soyad ile medeni durum/cinsiyet sorgusu yap"""
    name = name.strip().upper()
    surname = surname.strip().upper()
    
    if not name or not surname:
        return {'success': False, 'error': 'name ve surname gerekli'}
    
    cache_key = f"ad_medenicinsiyet_{name}_{surname}_{il}_{adres}"
    cached = get_from_cache(cache_key)
    if cached:
        print(f"📦 Cache hit for ad_medenicinsiyet: {name} {surname}")
        return cached
    
    command = f"/ad {name} {surname}"
    if il:
        command += f" -il {il}"
    if adres:
        command += f" -adres {adres}"
    
    print(f"🚀 Executing ad_medenicinsiyet command: {command}")
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {
            'success': False,
            'query': command,
            'error': raw_text
        }
    else:
        data = parse_ad_medenicinsiyet_response(raw_text)
        
        if data.get('MedeniDurum') or data.get('Cinsiyet'):
            # 🔥 GÜNCELLENDİ: build_simple_structured_json kullan
            result = build_simple_structured_json(data)
            result['query'] = command
        else:
            result = {
                'success': False,
                'query': command,
                'error': 'Medeni durum/cinsiyet bilgisi bulunamadı',
                'data': data
            }
    
    add_to_cache(cache_key, result)
    return result

# ========== ÇIKTI FORMATI ==========
def get_output_format():
    """Çıktı formatını belirle"""
    format_param = request.args.get('format', 'json').lower()
    if format_param in ['text', 'txt', 'plain']:
        return 'text'
    return 'json'

# ========== ENDPOINT'LER ==========

# ANA SAYFA
@app.route('/')
def index():
    """Home page"""
    html = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>🔍 TC Sorgu API - Tüm Endpointler</title>
<style>
body {
font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
margin: 0;
padding: 20px;
background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
min-height: 100vh;
}
.container {
max-width: 1200px;
margin: 0 auto;
background: white;
padding: 30px;
border-radius: 15px;
box-shadow: 0 10px 30px rgba(0,0,0,0.2);
}
h1 {
color: #333;
text-align: center;
margin-bottom: 10px;
}
h2 {
color: #495057;
margin-top: 30px;
padding-bottom: 10px;
border-bottom: 2px solid #6c757d;
}
.grid {
display: grid;
grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
gap: 20px;
margin-top: 20px;
}
.endpoint {
background: #f8f9fa;
padding: 15px;
border-left: 5px solid #007bff;
border-radius: 8px;
}
.new-badge {
background: #28a745;
color: white;
padding: 3px 8px;
border-radius: 12px;
font-size: 0.75em;
margin-left: 10px;
}
code {
background: #e9ecef;
padding: 3px 8px;
border-radius: 4px;
font-family: 'Courier New', monospace;
color: #d63384;
font-size: 0.9em;
display: block;
margin: 5px 0;
overflow-x: auto;
}
.test-link {
display: inline-block;
background: #28a745;
color: white;
padding: 6px 12px;
border-radius: 5px;
margin-top: 8px;
text-decoration: none !important;
font-size: 0.85em;
margin-right: 5px;
}
.test-link.json {
background: #007bff;
}
.test-link.text {
background: #17a2b8;
}
.test-link:hover {
opacity: 0.9;
color: white;
}
.format-info {
background: #fff3cd;
border: 1px solid #ffeaa7;
border-radius: 5px;
padding: 10px;
margin: 15px 0;
font-size: 0.9em;
}
.footer {
text-align: center;
margin-top: 40px;
color: #6c757d;
font-size: 0.9em;
padding-top: 20px;
border-top: 1px solid #dee2e6;
}
</style>
</head>
<body>
<div class="container">
<h1><span>🔍</span> TC Sorgu API <span style="font-size: 0.5em; background: #28a745; color: white; padding: 5px 10px; border-radius: 20px;">27 ENDPOINT</span></h1>
<p style="text-align: center; color: #666;">Telegram bot üzerinden gelişmiş sorgulama API'sı</p>

<div class="format-info">  
            <strong>📝 Çıktı Formatları:</strong><br>  
            • <strong>JSON Format:</strong> Varsayılan format (?format=json veya parametre yok)<br>  
            • <strong>Text Format:</strong> <code>?format=text</code> parametresi ekleyin<br>  
        </div>
        
        <h2>🆕 YENİ ENDPOINT'LER - İŞE GİRİŞ (2 Adet)</h2>
        <div class="grid">
            <div class="endpoint">
                <h4>İşe Giriş Sorgusu (Ad Soyad) <span class="new-badge">YENİ</span></h4>
                <code>GET /isegiris?name=EYMEN&surname=YAVUZ</code>
                <a href="/isegiris?name=EYMEN&surname=YAVUZ" target="_blank" class="test-link json">JSON Test</a>
                <a href="/isegiris?name=EYMEN&surname=YAVUZ&format=text" target="_blank" class="test-link text">Text Test</a>
            </div>
            
            <div class="endpoint">
                <h4>İşe Giriş Sorgusu (TC) <span class="new-badge">YENİ</span></h4>
                <code>GET /tc-isegiris?tc=11111111110</code>
                <a href="/tc-isegiris?tc=11111111110" target="_blank" class="test-link json">JSON Test</a>
                <a href="/tc-isegiris?tc=11111111110&format=text" target="_blank" class="test-link text">Text Test</a>
            </div>
        </div>
        
        <h2>🏠 İKAMETGAH SORGULARI (2 Adet)</h2>
        <div class="grid">
            <div class="endpoint">
                <h4>İkametgah Sorgusu (Ad Soyad) <span class="new-badge">YENİ</span></h4>
                <code>GET /ikametgah?name=EYMEN&surname=YAVUZ</code>
                <a href="/ikametgah?name=EYMEN&surname=YAVUZ" target="_blank" class="test-link json">JSON Test</a>
                <a href="/ikametgah?name=EYMEN&surname=YAVUZ&format=text" target="_blank" class="test-link text">Text Test</a>
            </div>
            
            <div class="endpoint">
                <h4>İkametgah Sorgusu (TC) <span class="new-badge">YENİ</span></h4>
                <code>GET /tc-ikametgah?tc=11111111110</code>
                <a href="/tc-ikametgah?tc=11111111110" target="_blank" class="test-link json">JSON Test</a>
                <a href="/tc-ikametgah?tc=11111111110&format=text" target="_blank" class="test-link text">Text Test</a>
            </div>
        </div>
        
        <h2>🧬 AİLE/BİREY SIRA SORGULARI (2 Adet)</h2>
        <div class="grid">
            <div class="endpoint">
                <h4>Aile/Birey Sıra Sorgusu (Ad Soyad) <span class="new-badge">YENİ</span></h4>
                <code>GET /ailebirey?name=EYMEN&surname=YAVUZ</code>
                <a href="/ailebirey?name=EYMEN&surname=YAVUZ" target="_blank" class="test-link json">JSON Test</a>
                <a href="/ailebirey?name=EYMEN&surname=YAVUZ&format=text" target="_blank" class="test-link text">Text Test</a>
            </div>
            
            <div class="endpoint">
                <h4>Aile/Birey Sıra Sorgusu (TC) <span class="new-badge">YENİ</span></h4>
                <code>GET /tc-ailebirey?tc=11111111110</code>
                <a href="/tc-ailebirey?tc=11111111110" target="_blank" class="test-link json">JSON Test</a>
                <a href="/tc-ailebirey?tc=11111111110&format=text" target="_blank" class="test-link text">Text Test</a>
            </div>
        </div>
        
        <h2>💍 MEDENİ DURUM/CİNSİYET SORGULARI (2 Adet)</h2>
        <div class="grid">
            <div class="endpoint">
                <h4>Medeni Durum/Cinsiyet Sorgusu (Ad Soyad) <span class="new-badge">YENİ</span></h4>
                <code>GET /medenicinsiyet?name=EYMEN&surname=YAVUZ</code>
                <a href="/medenicinsiyet?name=EYMEN&surname=YAVUZ" target="_blank" class="test-link json">JSON Test</a>
                <a href="/medenicinsiyet?name=EYMEN&surname=YAVUZ&format=text" target="_blank" class="test-link text">Text Test</a>
            </div>
            
            <div class="endpoint">
                <h4>Medeni Durum/Cinsiyet Sorgusu (TC) <span class="new-badge">YENİ</span></h4>
                <code>GET /tc-medenicinsiyet?tc=11111111110</code>
                <a href="/tc-medenicinsiyet?tc=11111111110" target="_blank" class="test-link json">JSON Test</a>
                <a href="/tc-medenicinsiyet?tc=11111111110&format=text" target="_blank" class="test-link text">Text Test</a>
            </div>
        </div>
        
        <h2>👤 KİŞİ SORGULARI (3 Adet)</h2>
        <div class="grid">
            <div class="endpoint">
                <h4>Ad Soyad Sorgusu</h4>
                <code>GET /query?name=EYMEN&surname=YAVUZ</code>
                <a href="/query?name=EYMEN&surname=YAVUZ" target="_blank" class="test-link json">JSON Test</a>
                <a href="/query?name=EYMEN&surname=YAVUZ&format=text" target="_blank" class="test-link text">Text Test</a>
            </div>
            
            <div class="endpoint">
                <h4>Ad Soyad (Alternatif)</h4>
                <code>GET /ad?name=EYMEN&surname=YAVUZ</code>
                <a href="/ad?name=EYMEN&surname=YAVUZ" target="_blank" class="test-link json">JSON Test</a>
            </div>
            
            <div class="endpoint">
                <h4>TC Sorgusu (Detaylı)</h4>
                <code>GET /tc?tc=11111111110</code>
                <a href="/tc?tc=11111111110" target="_blank" class="test-link json">JSON Test</a>
                <a href="/tc?tc=11111111110&format=text" target="_blank" class="test-link text">Text Test</a>
            </div>
        </div>
        
        <h2>📱 İLETİŞİM SORGULARI (3 Adet)</h2>
        <div class="grid">
            <div class="endpoint">
                <h4>GSM Sorgusu</h4>
                <code>GET /gsm?gsm=5346149118</code>
                <a href="/gsm?gsm=5346149118" target="_blank" class="test-link json">JSON Test</a>
                <a href="/gsm?gsm=5346149118&format=text" target="_blank" class="test-link text">Text Test</a>
            </div>
            
            <div class="endpoint">
                <h4>GSM2 Sorgusu</h4>
                <code>GET /gsm2?gsm=5346149118</code>
                <a href="/gsm2?gsm=5346149118" target="_blank" class="test-link json">JSON Test</a>
            </div>
            
            <div class="endpoint">
                <h4>Plaka Sorgusu</h4>
                <code>GET /plaka?plaka=34AKP34</code>
                <a href="/plaka?plaka=34AKP34" target="_blank" class="test-link json">JSON Test</a>
                <a href="/plaka?plaka=34AKP34&format=text" target="_blank" class="test-link text">Text Test</a>
            </div>
        </div>
        
        <h2>👨‍👩‍👧‍👦 AİLE SORGULARI (4 Adet)</h2>
        <div class="grid">
            <div class="endpoint">
                <h4>Aile Sorgusu</h4>
                <code>GET /aile?tc=11111111110</code>
                <a href="/aile?tc=11111111110" target="_blank" class="test-link json">JSON Test</a>
            </div>
            
            <div class="endpoint">
                <h4>Sülale Sorgusu</h4>
                <code>GET /sulale?tc=11111111110</code>
                <a href="/sulale?tc=11111111110" target="_blank" class="test-link json">JSON Test</a>
            </div>
            
            <div class="endpoint">
                <h4>Hane Sorgusu</h4>
                <code>GET /hane?tc=11111111110</code>
                <a href="/hane?tc=11111111110" target="_blank" class="test-link json">JSON Test</a>
            </div>
            
            <div class="endpoint">
                <h4>İşyeri Sorgusu</h4>
                <code>GET /isyeri?tc=11111111110</code>
                <a href="/isyeri?tc=11111111110" target="_blank" class="test-link json">JSON Test</a>
            </div>
        </div>
        
        <h2>📊 DİĞER SORGULAR (3 Adet)</h2>
        <div class="grid">
            <div class="endpoint">
                <h4>TC2 Sorgusu</h4>
                <code>GET /tc2?tc=11111111110</code>
                <a href="/tc2?tc=11111111110" target="_blank" class="test-link json">JSON Test</a>
            </div>
            
            <div class="endpoint">
                <h4>Vesika Sorgusu</h4>
                <code>GET /vesika?tc=11111111110</code>
                <a href="/vesika?tc=11111111110" target="_blank" class="test-link json">JSON Test</a>
            </div>
            
            <div class="endpoint">
                <h4>Text Output (Legacy)</h4>
                <code>GET /text?name=EYMEN&surname=YAVUZ</code>
                <a href="/text?name=EYMEN&surname=YAVUZ" target="_blank" class="test-link">Test Et</a>
            </div>
        </div>
        
        <h2>🔧 YARDIMCI ENDPOINT'LER (5 Adet)</h2>
        <div class="grid">
            <div class="endpoint">
                <h4>Raw Output</h4>
                <code>GET /raw?name=EYMEN&surname=YAVUZ</code>
                <a href="/raw?name=EYMEN&surname=YAVUZ" target="_blank" class="test-link">Test Et</a>
            </div>
            
            <div class="endpoint">
                <h4>Test</h4>
                <code>GET /test</code>
                <a href="/test" target="_blank" class="test-link json">Test Et</a>
            </div>
            
            <div class="endpoint">
                <h4>Health</h4>
                <code>GET /health</code>
                <a href="/health" target="_blank" class="test-link json">Test Et</a>
            </div>
            
            <div class="endpoint">
                <h4>Ana Sayfa</h4>
                <code>GET /</code>
                <a href="/" target="_blank" class="test-link">Test Et</a>
            </div>
        </div>
        
        <div class="footer">
            <p><strong>📊 TOPLAM: 27 ENDPOINT</strong> (8 yeni + 19 mevcut)</p>
            <p><strong>⚠️ Not:</strong> Tüm endpoint'ler UTF-8 encoding kullanır. Cache süresi 5 dakikadır.</p>
            <p>© 2024 TC Sorgu API - Tüm Endpointler Aktif</p>
        </div>
    </div>
</body>
</html>
"""
    return html

# YENİ ENDPOINT'LER - Ad Soyad ile
@app.route('/isegiris', methods=['GET'])
def api_isegiris():
    """Ad soyad ile işe giriş sorgusu"""
    if not app_started:
        init_app()
    
    name = request.args.get('name', '').strip().upper()
    surname = request.args.get('surname', '').strip().upper()
    
    if not name or not surname:
        if get_output_format() == 'text':
            return Response('❌ Hata: name ve surname gerekli', content_type='text/plain; charset=utf-8')
        return jsonify({'success': False, 'error': 'name ve surname gerekli'}), 400
    
    il = request.args.get('il', '').strip().title()
    adres = request.args.get('adres', '').strip()
    
    result = handle_ad_isegiris_query(name, surname, il, adres)
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"{name} {surname} - İşe Giriş Bilgileri"
            text_output = format_isegiris_to_text(result['data'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)

@app.route('/ikametgah', methods=['GET'])
def api_ikametgah():
    """Ad soyad ile ikametgah sorgusu"""
    if not app_started:
        init_app()
    
    name = request.args.get('name', '').strip().upper()
    surname = request.args.get('surname', '').strip().upper()
    
    if not name or not surname:
        if get_output_format() == 'text':
            return Response('❌ Hata: name ve surname gerekli', content_type='text/plain; charset=utf-8')
        return jsonify({'success': False, 'error': 'name ve surname gerekli'}), 400
    
    il = request.args.get('il', '').strip().title()
    adres = request.args.get('adres', '').strip()
    
    result = handle_ad_ikametgah_query(name, surname, il, adres)
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"{name} {surname} - İkametgah Bilgisi"
            text_output = format_ikametgah_to_text(result['data'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)

@app.route('/ailebirey', methods=['GET'])
def api_ailebirey():
    """Ad soyad ile aile/birey sıra sorgusu"""
    if not app_started:
        init_app()
    
    name = request.args.get('name', '').strip().upper()
    surname = request.args.get('surname', '').strip().upper()
    
    if not name or not surname:
        if get_output_format() == 'text':
            return Response('❌ Hata: name ve surname gerekli', content_type='text/plain; charset=utf-8')
        return jsonify({'success': False, 'error': 'name ve surname gerekli'}), 400
    
    il = request.args.get('il', '').strip().title()
    adres = request.args.get('adres', '').strip()
    
    result = handle_ad_ailebirey_query(name, surname, il, adres)
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"{name} {surname} - Aile/Birey Sıra Bilgisi"
            text_output = format_ailebirey_to_text(result['data'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)

@app.route('/medenicinsiyet', methods=['GET'])
def api_medenicinsiyet():
    """Ad soyad ile medeni durum/cinsiyet sorgusu"""
    if not app_started:
        init_app()
    
    name = request.args.get('name', '').strip().upper()
    surname = request.args.get('surname', '').strip().upper()
    
    if not name or not surname:
        if get_output_format() == 'text':
            return Response('❌ Hata: name ve surname gerekli', content_type='text/plain; charset=utf-8')
        return jsonify({'success': False, 'error': 'name ve surname gerekli'}), 400
    
    il = request.args.get('il', '').strip().title()
    adres = request.args.get('adres', '').strip()
    
    result = handle_ad_medenicinsiyet_query(name, surname, il, adres)
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"{name} {surname} - Medeni Durum/Cinsiyet Bilgisi"
            text_output = format_medenicinsiyet_to_text(result['data'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)

# YENİ ENDPOINT'LER - TC ile
@app.route('/tc-isegiris', methods=['GET'])
def api_tc_isegiris():
    """TC ile işe giriş sorgusu"""
    if not app_started:
        init_app()
    
    tc = request.args.get('tc', '').strip()
    
    result = handle_tc_isegiris_query(tc)
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"TC: {tc} - İşe Giriş Bilgileri"
            text_output = format_isegiris_to_text(result['data'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)

@app.route('/tc-ikametgah', methods=['GET'])
def api_tc_ikametgah():
    """TC ile ikametgah sorgusu"""
    if not app_started:
        init_app()
    
    tc = request.args.get('tc', '').strip()
    
    result = handle_tc_ikametgah_query(tc)
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"TC: {tc} - İkametgah Bilgisi"
            text_output = format_ikametgah_to_text(result['data'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)

@app.route('/tc-ailebirey', methods=['GET'])
def api_tc_ailebirey():
    """TC ile aile/birey sıra sorgusu"""
    if not app_started:
        init_app()
    
    tc = request.args.get('tc', '').strip()
    
    result = handle_tc_ailebirey_query(tc)
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"TC: {tc} - Aile/Birey Sıra Bilgisi"
            text_output = format_ailebirey_to_text(result['data'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)

@app.route('/tc-medenicinsiyet', methods=['GET'])
def api_tc_medenicinsiyet():
    """TC ile medeni durum/cinsiyet sorgusu"""
    if not app_started:
        init_app()
    
    tc = request.args.get('tc', '').strip()
    
    result = handle_tc_medenicinsiyet_query(tc)
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"TC: {tc} - Medeni Durum/Cinsiyet Bilgisi"
            text_output = format_medenicinsiyet_to_text(result['data'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)

# MEVCUT ENDPOINT'LER (GÜNCELLENMİŞ)
@app.route('/query', methods=['GET'])
def api_query():
    """Ana sorgu endpoint'i - Ad soyad ile"""
    if not app_started:
        init_app()
    
    name = request.args.get('name', '').strip().upper()
    surname = request.args.get('surname', '').strip().upper()
    
    if not name or not surname:
        if get_output_format() == 'text':
            return Response('❌ Hata: name ve surname gerekli', content_type='text/plain; charset=utf-8')
        return jsonify({'success': False, 'error': 'name ve surname gerekli'}), 400
    
    il = request.args.get('il', '').strip().title()
    adres = request.args.get('adres', '').strip()
    
    result = handle_ad_detayli_query(name, surname, il, adres)
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"{name} {surname} Sorgu Sonuçları"
            text_output = format_tc_detayli_to_text(result['data'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)

@app.route('/ad', methods=['GET'])
def api_ad():
    """Ad soyad sorgusu (query ile aynı)"""
    return api_query()

@app.route('/tc', methods=['GET'])
def api_tc():
    """TC sorgusu - Detaylı"""
    if not app_started:
        init_app()
    
    tc = request.args.get('tc', '').strip()
    
    result = handle_tc_detayli_query(tc)
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"TC: {tc} Sorgu Sonuçları"
            text_output = format_tc_detayli_to_text(result['data'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)

@app.route('/gsm', methods=['GET'])
def api_gsm():
    """GSM sorgusu"""
    if not app_started:
        init_app()
    
    gsm = request.args.get('gsm', '').strip()
    gsm = clean_gsm(gsm)
    
    if not gsm:
        if get_output_format() == 'text':
            return Response('❌ Hata: Geçerli bir telefon numarası giriniz', content_type='text/plain; charset=utf-8')
        return jsonify({'success': False, 'error': 'Geçerli bir telefon numarası giriniz'}), 400
    
    cache_key = f"gsm_{gsm}"
    cached = get_from_cache(cache_key)
    if cached:
        print(f"📦 Cache hit for gsm: {gsm}")
        if get_output_format() == 'text':
            if cached['success']:
                title = f"GSM: {gsm} Sorgu Sonuçları"
                text_output = format_tc_detayli_to_text(cached['data'], title)
                return Response(text_output, content_type='text/plain; charset=utf-8')
            else:
                return Response(f"❌ Hata: {cached.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
        return jsonify(cached)
    
    command = f"/gsm {gsm}"
    print(f"🚀 Executing command: {command}")
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {
            'success': False,
            'query': command,
            'error': raw_text
        }
    else:
        data = parse_tc_detayli_response(raw_text)
        
        if data.get('TC'):
            result = build_structured_json(data)
            result['query'] = command
        else:
            result = {
                'success': False,
                'query': command,
                'error': 'Kayıt bulunamadı',
                'data': data
            }
    
    add_to_cache(cache_key, result)
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"GSM: {gsm} Sorgu Sonuçları"
            text_output = format_tc_detayli_to_text(result['data'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)

@app.route('/gsm2', methods=['GET'])
def api_gsm2():
    """GSM2 sorgusu"""
    if not app_started:
        init_app()
    
    gsm = request.args.get('gsm', '').strip()
    gsm = clean_gsm(gsm)
    
    if not gsm:
        return jsonify({'success': False, 'error': 'Geçerli bir telefon numarası giriniz'}), 400
    
    cache_key = f"gsm2_{gsm}"
    cached = get_from_cache(cache_key)
    if cached:
        return jsonify(cached)
    
    command = f"/gsm2 {gsm}"
    print(f"🚀 Executing command: {command}")
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {
            'success': False,
            'query': command,
            'error': raw_text
        }
    else:
        data = parse_tc_detayli_response(raw_text)
        
        if data.get('TC'):
            result = build_structured_json(data)
            result['query'] = command
        else:
            result = {
                'success': False,
                'query': command,
                'error': 'Kayıt bulunamadı',
                'data': data
            }
    
    add_to_cache(cache_key, result)
    return jsonify(result)

@app.route('/plaka', methods=['GET'])
def api_plaka():
    """Plaka sorgusu"""
    if not app_started:
        init_app()
    
    plaka = request.args.get('plaka', '').strip()
    plaka = clean_plaka(plaka)
    
    if not plaka:
        if get_output_format() == 'text':
            return Response('❌ Hata: Geçerli bir plaka numarası giriniz', content_type='text/plain; charset=utf-8')
        return jsonify({'success': False, 'error': 'Geçerli bir plaka numarası giriniz'}), 400
    
    cache_key = f"plaka_{plaka}"
    cached = get_from_cache(cache_key)
    if cached:
        print(f"📦 Cache hit for plaka: {plaka}")
        if get_output_format() == 'text':
            if cached['success']:
                title = f"Plaka: {plaka} Sorgu Sonuçları"
                text_output = format_tc_detayli_to_text(cached['data'], title)
                return Response(text_output, content_type='text/plain; charset=utf-8')
            else:
                return Response(f"❌ Hata: {cached.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
        return jsonify(cached)
    
    command = f"/plaka {plaka}"
    print(f"🚀 Executing command: {command}")
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {
            'success': False,
            'query': command,
            'error': raw_text
        }
    else:
        data = parse_tc_detayli_response(raw_text)
        
        if data.get('TC'):
            result = build_structured_json(data)
            result['query'] = command
        else:
            result = {
                'success': False,
                'query': command,
                'error': 'Kayıt bulunamadı',
                'data': data
            }
    
    add_to_cache(cache_key, result)
    
    if get_output_format() == 'text':
        if result['success']:
            title = f"Plaka: {plaka} Sorgu Sonuçları"
            text_output = format_tc_detayli_to_text(result['data'], title)
            return Response(text_output, content_type='text/plain; charset=utf-8')
        else:
            return Response(f"❌ Hata: {result.get('error', 'Bilinmeyen hata')}", content_type='text/plain; charset=utf-8')
    
    return jsonify(result)

@app.route('/aile', methods=['GET'])
def api_aile():
    """Aile sorgusu"""
    if not app_started:
        init_app()
    
    tc = request.args.get('tc', '').strip()
    tc = clean_tc(tc)
    
    if not tc:
        return jsonify({'success': False, 'error': 'Geçerli bir 11 haneli TC kimlik numarası giriniz'}), 400
    
    cache_key = f"aile_{tc}"
    cached = get_from_cache(cache_key)
    if cached:
        return jsonify(cached)
    
    command = f"/aile {tc}"
    print(f"🚀 Executing command: {command}")
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {
            'success': False,
            'query': command,
            'error': raw_text
        }
    else:
        data = parse_tc_detayli_response(raw_text)
        
        if data.get('TC'):
            result = build_structured_json(data)
            result['query'] = command
        else:
            result = {
                'success': False,
                'query': command,
                'error': 'Kayıt bulunamadı',
                'data': data
            }
    
    add_to_cache(cache_key, result)
    return jsonify(result)

@app.route('/sulale', methods=['GET'])
def api_sulale():
    """Sülale sorgusu"""
    if not app_started:
        init_app()
    
    tc = request.args.get('tc', '').strip()
    tc = clean_tc(tc)
    
    if not tc:
        return jsonify({'success': False, 'error': 'Geçerli bir 11 haneli TC kimlik numarası giriniz'}), 400
    
    cache_key = f"sulale_{tc}"
    cached = get_from_cache(cache_key)
    if cached:
        return jsonify(cached)
    
    command = f"/sulale {tc}"
    print(f"🚀 Executing command: {command}")
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {
            'success': False,
            'query': command,
            'error': raw_text
        }
    else:
        data = parse_tc_detayli_response(raw_text)
        
        if data.get('TC'):
            result = build_structured_json(data)
            result['query'] = command
        else:
            result = {
                'success': False,
                'query': command,
                'error': 'Kayıt bulunamadı',
                'data': data
            }
    
    add_to_cache(cache_key, result)
    return jsonify(result)

@app.route('/hane', methods=['GET'])
def api_hane():
    """Hane sorgusu"""
    if not app_started:
        init_app()
    
    tc = request.args.get('tc', '').strip()
    tc = clean_tc(tc)
    
    if not tc:
        return jsonify({'success': False, 'error': 'Geçerli bir 11 haneli TC kimlik numarası giriniz'}), 400
    
    cache_key = f"hane_{tc}"
    cached = get_from_cache(cache_key)
    if cached:
        return jsonify(cached)
    
    command = f"/hane {tc}"
    print(f"🚀 Executing command: {command}")
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {
            'success': False,
            'query': command,
            'error': raw_text
        }
    else:
        data = parse_tc_detayli_response(raw_text)
        
        if data.get('TC'):
            result = build_structured_json(data)
            result['query'] = command
        else:
            result = {
                'success': False,
                'query': command,
                'error': 'Kayıt bulunamadı',
                'data': data
            }
    
    add_to_cache(cache_key, result)
    return jsonify(result)

@app.route('/isyeri', methods=['GET'])
def api_isyeri():
    """İşyeri sorgusu"""
    if not app_started:
        init_app()
    
    tc = request.args.get('tc', '').strip()
    tc = clean_tc(tc)
    
    if not tc:
        return jsonify({'success': False, 'error': 'Geçerli bir 11 haneli TC kimlik numarası giriniz'}), 400
    
    cache_key = f"isyeri_{tc}"
    cached = get_from_cache(cache_key)
    if cached:
        return jsonify(cached)
    
    command = f"/isyeri {tc}"
    print(f"🚀 Executing command: {command}")
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {
            'success': False,
            'query': command,
            'error': raw_text
        }
    else:
        data = parse_tc_detayli_response(raw_text)
        
        if data.get('TC'):
            result = build_structured_json(data)
            result['query'] = command
        else:
            result = {
                'success': False,
                'query': command,
                'error': 'Kayıt bulunamadı',
                'data': data
            }
    
    add_to_cache(cache_key, result)
    return jsonify(result)

@app.route('/tc2', methods=['GET'])
def api_tc2():
    """TC2 sorgusu"""
    if not app_started:
        init_app()
    
    tc = request.args.get('tc', '').strip()
    tc = clean_tc(tc)
    
    if not tc:
        return jsonify({'success': False, 'error': 'Geçerli bir 11 haneli TC kimlik numarası giriniz'}), 400
    
    cache_key = f"tc2_{tc}"
    cached = get_from_cache(cache_key)
    if cached:
        return jsonify(cached)
    
    command = f"/tc2 {tc}"
    print(f"🚀 Executing command: {command}")
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {
            'success': False,
            'query': command,
            'error': raw_text
        }
    else:
        data = parse_tc_detayli_response(raw_text)
        
        if data.get('TC'):
            result = build_structured_json(data)
            result['query'] = command
        else:
            result = {
                'success': False,
                'query': command,
                'error': 'Kayıt bulunamadı',
                'data': data
            }
    
    add_to_cache(cache_key, result)
    return jsonify(result)

@app.route('/vesika', methods=['GET'])
def api_vesika():
    """Vesika sorgusu"""
    if not app_started:
        init_app()
    
    tc = request.args.get('tc', '').strip()
    tc = clean_tc(tc)
    
    if not tc:
        return jsonify({'success': False, 'error': 'Geçerli bir 11 haneli TC kimlik numarası giriniz'}), 400
    
    cache_key = f"vesika_{tc}"
    cached = get_from_cache(cache_key)
    if cached:
        return jsonify(cached)
    
    command = f"/vesika {tc}"
    print(f"🚀 Executing command: {command}")
    raw_text = sync_query_bot(command)
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        result = {
            'success': False,
            'query': command,
            'error': raw_text
        }
    else:
        data = parse_tc_detayli_response(raw_text)
        
        if data.get('TC'):
            result = build_structured_json(data)
            result['query'] = command
        else:
            result = {
                'success': False,
                'query': command,
                'error': 'Kayıt bulunamadı',
                'data': data
            }
    
    add_to_cache(cache_key, result)
    return jsonify(result)

@app.route('/text', methods=['GET'])
def api_text():
    """Text output endpoint (legacy)"""
    if not app_started:
        init_app()
    
    name = request.args.get('name', '') or request.args.get('first_name', '')
    surname = request.args.get('surname', '') or request.args.get('last_name', '')
    name = name.strip().upper()
    surname = surname.strip().upper()
    
    if not name or not surname:
        return Response('❌ Hata: name ve surname gerekli', content_type='text/plain; charset=utf-8')
    
    command = f"/ad {name} {surname}"
    print(f"🚀 Executing command: {command}")
    raw_text = sync_query_bot(command)
    print(f"📊 Raw response length: {len(raw_text)}")
    
    if raw_text.startswith("Error:") or raw_text.startswith("❌"):
        return Response(f'❌ Hata: {raw_text}', content_type='text/plain; charset=utf-8')
    
    data = parse_tc_detayli_response(raw_text)
    
    if not data or not data.get('TC'):
        return Response(f'❌ {name} {surname} için kayıt bulunamadı.', content_type='text/plain; charset=utf-8')
    
    text_output = format_tc_detayli_to_text(data, f"{name} {surname} Sorgu Sonucu")
    return Response(text_output, content_type='text/plain; charset=utf-8')

@app.route('/raw', methods=['GET'])
def api_raw():
    """Ham veri endpoint'i"""
    if not app_started:
        init_app()
    
    name = request.args.get('name', '') or request.args.get('first_name', '')
    surname = request.args.get('surname', '') or request.args.get('last_name', '')
    name = name.strip().upper()
    surname = surname.strip().upper()
    
    if not name or not surname:
        return Response('❌ Hata: name ve surname gerekli', content_type='text/plain; charset=utf-8')
    
    command = f"/ad {name} {surname}"
    print(f"🚀 Executing command: {command}")
    raw_text = sync_query_bot(command)
    print(f"📊 Raw response length: {len(raw_text)}")
    
    output = f"🔍 HAM VERİ: {name} {surname}\n"
    output += "="*60 + "\n\n"
    output += raw_text[:2000] + ("\n\n[...truncated...]" if len(raw_text) > 2000 else "")
    
    return Response(output, content_type='text/plain; charset=utf-8')

@app.route('/test', methods=['GET'])
def api_test():
    """Test endpoint"""
    return jsonify({
        'status': '✅ API çalışıyor',
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'app_started': app_started,
        'cache_size': len(result_cache),
        'total_endpoints': 27,
        'new_endpoints': [
            '/isegiris (Ad Soyad)',
            '/ikametgah (Ad Soyad)',
            '/ailebirey (Ad Soyad)',
            '/medenicinsiyet (Ad Soyad)',
            '/tc-isegiris',
            '/tc-ikametgah',
            '/tc-ailebirey',
            '/tc-medenicinsiyet'
        ]
    })

@app.route('/health', methods=['GET'])
def api_health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'service': 'TC Sorgu API',
        'total_endpoints': 27,
        'text_support': True
    })

# ========== APPLICATION LIFECYCLE ==========
print("🚀 Application starting...")
init_app()

if __name__ == '__main__':
    print(f"🌐 Server starting on port {PORT}")
    print("="*60)
    print("📋 TOPLAM 27 ENDPOINT AKTİF")
    print("="*60)
    print("\n🆕 YENİ ENDPOINT'LER (Ad Soyad ile):")
    print("  📅 /isegiris - İşe giriş sorgusu")
    print("  🏠 /ikametgah - İkametgah sorgusu")
    print("  🧬 /ailebirey - Aile/Birey sıra sorgusu")
    print("  💍 /medenicinsiyet - Medeni durum/cinsiyet sorgusu")
    print("\n🆕 YENİ ENDPOINT'LER (TC ile):")
    print("  📅 /tc-isegiris - İşe giriş sorgusu")
    print("  🏠 /tc-ikametgah - İkametgah sorgusu")
    print("  🧬 /tc-ailebirey - Aile/Birey sıra sorgusu")
    print("  💍 /tc-medenicinsiyet - Medeni durum/cinsiyet sorgusu")
    print("\n📋 MEVCUT ENDPOINT'LER (19 Adet):")
    print("  👤 /query, /ad - Ad soyad sorgusu")
    print("  🪪 /tc - Detaylı TC sorgusu")
    print("  📱 /gsm, /gsm2 - GSM sorguları")
    print("  🚗 /plaka - Plaka sorgusu")
    print("  👨‍👩‍👧‍👦 /aile, /sulale, /hane, /isyeri - Aile sorguları")
    print("  📊 /tc2, /vesika - Diğer sorgular")
    print("  🔧 /text, /raw, /test, /health, / - Yardımcılar")
    print("="*60)
    print("📝 Tüm endpoint'lere ?format=text parametresi ekleyerek text çıktısı alabilirsiniz!")
    print("="*60)
    
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
