import asyncio
import os
import tempfile
from typing import Dict

import pyautogui
from google.genai import types

from database import execute_sql_query, DatabaseError
from utils import _create_error_response

google_search_tool = types.Tool(
    google_search=types.GoogleSearch()
)

db_gukar_tool = types.FunctionDeclaration(
    name="db_gukar_tool",
    description="""
        Tool ini digunakan untuk mengambil detail data guru atau karyawan dari database. Gunakan tool ini HANYA untuk query SELECT. Tabelnya adalah `gukar` dengan kolom-kolom sebagai berikut:
        - nama.
        - gender: (String, 'L' atau 'P').
        - golongan.
        - nip: Nomor Induk Pegawai.
        - tempat_lahir.
        - tanggal_lahir: (string).
        - pendidikan_terakhir:  Pendidikan terakhir.
        - tahun_lulus: Tahun lulus pendidikan terakhir.
        - bidang_studi: Bidang studi yang dikuasai.
        - mengajar: Mata pelajaran yang diajar atau jabatan (karyawan, kepala sekolah dll)
        - agama: Agama.
        - no_hp: Nomor HP.
        - email: Email.
        - desa: Nama desa.
        - alamat: Alamat lengkap.

        kolom 'mengajar' tidak hanya berisi mapel yang diajar oleh guru, tapi juga bisa berisi jabatan guru atau jabatan karyawan.
        jangan pernah tampilkan data Ibu kandung dan NIK guru.
    """,
    parameters=types.Schema(
        type = "OBJECT",
        properties = {
            "sqlQuery": types.Schema(
                type= "STRING",
                description= "query SQL yang akan dieksekusi. Pastikan query adalah SELECT. Gunakan tabel 'gukar'. Contoh: SELECT `nama`, `tempat_lahir`, `tanggal_lahir`, `mengajar` FROM `gukar` WHERE `nama` LIKE '%nama_yang_dicari%'",
            )
        },
        required = ["sqlQuery"]
    )
)

db_siswa_tool = types.FunctionDeclaration(
    name="db_siswa_tool",
    description="""
        Gunakan tool ini untuk mencari data siswa atau menghitung jumlah siswa berdasarkan nama, NISN (Nomor Induk Siswa Nasional), NIPD (Nomor Induk Peserta Didik), atau rombel_saat_ini (kelas).
        Tool ini secara otomatis akan melakukan pencarian fuzzy (LIKE '%%term%%') pada kolom nama untuk mengatasi kesalahan ketik atau nama parsial, dan pencocokan persis untuk NISN dan NIPD.
        Jika parameter aggregate diisi, tool ini akan mengembalikan hasil agregasi (misal jumlah siswa). Jika tidak, tool ini akan mengembalikan kolom: nama, jk (jenis kelamin), nisn, nipd, rombel_saat_ini.
    """,
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "search_term": types.Schema(
                type="STRING",
                description="Nama (atau bagian dari nama), NISN, atau NIPD siswa yang akan dicari. Contoh: 'budi', '0012345678'. bisa juga null jika mencari berdasarkan kelas",
            ),
            "rombel_saat_ini": types.Schema(
                type="STRING",
                description="Nama rombel atau kelas siswa saat ini. Contoh: 'X 1', 'XI 2'. bisa juga null jika mencari berdasarkan nama, nisn atau nipd saja",
            ),
            "aggregate": types.Schema(
                type="STRING",
                description="Jenis agregasi yang akan dilakukan. Saat ini hanya mendukung 'count'. Contoh: 'count'",
            ),
        },
        required=[]
    )
)

db_update_tool = types.FunctionDeclaration(
    name="db_update_tool",
    description="""
        Tool ini digunakan untuk mengupdate satu atau beberapa kolom pada sebuah tabel di database berdasarkan key (where condition).
        PENTING: pastikan where condition nya valid dan tidak salah.
    """,
    parameters=types.Schema(
        type= "OBJECT",
        properties= {
            "table_name": types.Schema(
                type= "STRING",
                description= "Nama tabel yang akan diupdate. Contoh: 'siswa', 'gukar'",
            ),
            "column_names": types.Schema(
                type= "ARRAY",
                items= {"type": "STRING"},
                description= "Array yang berisi nama-nama kolom yang akan diupdate. Contoh: ['no_seri_ijazah', 'tahun_lulus']",
            ),
            "column_values": types.Schema(
                type= "ARRAY",
                items= {"type": "STRING"},
                description= "Array yang berisi nilai-nilai baru untuk kolom-kolom yang diupdate. Contoh: ['ABC12345', '2023']. Pastikan urutannya sama dengan column_names.",
            ),
             "key": types.Schema(
                type= "STRING",
                description= "Kondisi WHERE untuk update. contoh: `nisn` = '1234567890'",
            ),
        },
        required= ["table_name", "column_names", "column_values", "key"],
    ),
)

db_insert_tool = types.FunctionDeclaration(
    name="db_insert_tool",
    description="""
        Tool ini digunakan untuk menambahkan data baru ke sebuah tabel di database.
        PENTING: Pastikan data yang akan dimasukkan sudah valid dan sesuai dengan skema tabel.
    """,
    parameters=types.Schema(
        type= "OBJECT",
        properties= {
            "table_name": types.Schema(
                type= "STRING",
                description= "Nama tabel yang akan ditambahkan data. Contoh: 'siswa', 'gukar'",
            ),
            "column_names": types.Schema(
                type= "ARRAY",
                items= {"type": "STRING"},
                description= "Array yang berisi nama-nama kolom yang akan diisi datanya. Contoh: ['nisn', 'nama', 'jk']",
            ),
            "column_values": types.Schema(
                type= "ARRAY",
                items= {"type": "STRING"},
                description= "Array yang berisi nilai-nilai baru untuk kolom-kolom yang akan diisi. Contoh: ['1234567890', 'Nama Siswa', 'L']. Pastikan urutannya sama dengan column_names.",
            ),
        },
        required= ["table_name", "column_names", "column_values"],
    )
)

cctv_tool = types.FunctionDeclaration(
    name="cctv_tool",
    description="Gunakan tool ini untuk merestart cctv.",
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "command": types.Schema(
                type="STRING",
                description="Command untuk restart cctv",
                enum=["restart", "stop"]
            )
        },
        required=["command"]
    )
)

ss_tool = types.FunctionDeclaration(
    name="ss_tool",
    description="Gunakan tool ini untuk mengambil screenshot.",
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "command": types.Schema(
                type="STRING",
                description="Command untuk mengambil screenshot",
                enum=["screenshot"]
            ),
        },
        required=["command"]
    ),
)

db_tool = types.Tool(
    function_declarations=[db_gukar_tool, db_siswa_tool, db_update_tool, db_insert_tool],
)

extra_tools = types.Tool(
    function_declarations=[cctv_tool, ss_tool],
)

async def _handle_db_gukar_tool(args: Dict, db_pool) -> types.Part:
    tool_name = "db_gukar_tool"
    sql_query = args.get("sqlQuery")
    if not sql_query:
        return _create_error_response(tool_name, "sqlQuery tidak ditemukan.")
    
    if not sql_query.strip().upper().startswith("SELECT"):
        return _create_error_response(tool_name, "Tool ini hanya bisa digunakan untuk query SELECT.")
    
    try:
        query_result = await execute_sql_query(db_pool, sql_query)
        return types.Part.from_function_response(
            name=tool_name,
            response={'result': str(query_result)},
        )
    except DatabaseError as e:
        return _create_error_response(tool_name, f"Error executing database operation: {e}")

async def _handle_db_siswa_tool(args: Dict, db_pool) -> types.Part:
    tool_name = "db_siswa_tool"
    search_term = args.get("search_term")
    rombel_saat_ini = args.get("rombel_saat_ini")
    aggregate = args.get("aggregate")

    if not search_term and not rombel_saat_ini:
        return _create_error_response(tool_name, "Missing required arguments: search_term or rombel_saat_ini")

    if aggregate and aggregate.lower() == 'count':
        base_query = "SELECT COUNT(*) as total FROM siswa"
    else:
        base_query = "SELECT nama, jk, nisn, nipd, rombel_saat_ini FROM siswa"
    
    conditions = []
    params = []

    if search_term:
        conditions.append("(nama LIKE %s OR nisn = %s OR nipd = %s)")
        params.extend([f"%{search_term}%", search_term, search_term])

    if rombel_saat_ini:
        conditions.append("rombel_saat_ini = %s")
        params.append(rombel_saat_ini)

    if conditions:
        sql_query = f"{base_query} WHERE {' AND '.join(conditions)}"
    else:
        sql_query = base_query

    try:
        query_result = await execute_sql_query(db_pool, sql_query, params=tuple(params))
        return types.Part.from_function_response(
            name=tool_name,
            response={'result': str(query_result)},
        )
    except DatabaseError as e:
        return _create_error_response(tool_name, f"Error executing database operation: {e}")

async def _handle_db_update_tool(args: Dict, db_pool) -> types.Part:
    table_name = args.get("table_name")
    column_names = args.get("column_names")
    column_values = args.get("column_values")
    key = args.get("key")

    if not all([table_name, column_names, column_values, key]):
        return _create_error_response("db_update_tool", "Missing required arguments")
    if not isinstance(column_names, list) or not isinstance(column_values, list) or len(column_names) != len(column_values):
        return _create_error_response("db_update_tool", "column_names and column_values must be lists of the same length.")
    
    set_clause = ", ".join([f"`{col}` = '{val}'" for col, val in zip(column_names, column_values)])
    sql_query = f"UPDATE {table_name} SET {set_clause} WHERE {key}"
    try:
        query_result = await execute_sql_query(db_pool, sql_query)
        return types.Part.from_function_response(
            name="db_update_tool",
            response={'result': str(query_result)},
        )
    except DatabaseError as e:
        return _create_error_response("db_update_tool", f"Error executing database operation: {e}")

async def _handle_db_insert_tool(args: Dict, db_pool) -> types.Part:
    table_name = args.get("table_name")
    column_names = args.get("column_names")
    column_values = args.get("column_values")

    if not all([table_name, column_names, column_values]):
        return _create_error_response("db_insert_tool", "Missing required arguments")
    if not isinstance(column_names, list) or not isinstance(column_values, list) or len(column_names) != len(column_values):
        return _create_error_response("db_insert_tool", "column_names and column_values must be lists of the same length.")

    placeholders = ", ".join(["%s"] * len(column_names))
    columns = ", ".join([f"`{col}`" for col in column_names])
    sql_query = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"
    try:
        query_result = await execute_sql_query(db_pool, sql_query, params=tuple(column_values))
        return types.Part.from_function_response(
            name="db_insert_tool",
            response={'result': str(query_result)}
        )
    except DatabaseError as e:
        return _create_error_response("db_insert_tool", f"Error executing database operation: {e}")

async def _handle_cctv_tool(args: Dict) -> types.Part:
    try:
        process = await asyncio.create_subprocess_shell(
            'pm2 restart "Super Simpel NVR"',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            return types.Part.from_function_response(
                name="cctv_tool",
                response={"result": "Proses 'Super Simpel NVR' berhasil direstart."},
            )
        else:
            error_message = f"Error restarting 'Super Simpel NVR': {stderr.decode()}"
            return _create_error_response("cctv_tool", error_message)
    except Exception as e:
        return _create_error_response("cctv_tool", f"An unexpected error occurred: {e}")

async def _handle_ss_tool(args: Dict, client) -> types.Part:
    try:
        screenshot = pyautogui.screenshot()
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
            screenshot.save(tmp_file.name)
            temp_file_path = tmp_file.name
        uploaded_file = client.files.upload(file=temp_file_path)
        os.unlink(temp_file_path)
        
        return types.Part.from_function_response(
            name="ss_tool",
            response={"result": uploaded_file.uri}
        )
    except Exception as e:
        return types.Part.from_function_response(
            name="take_screenshot",
            response={"result": f"Error: {e}"}
        )

async def handle_tool_call(tool_call: types.FunctionCall, db_pool, client) -> types.Part:
    tool_name = tool_call.name
    args = tool_call.args
    try:
        if tool_name in ["db_gukar_tool", "db_siswa_tool", "db_update_tool", "db_insert_tool"]:
            handler = {
                "db_gukar_tool": _handle_db_gukar_tool,
                "db_siswa_tool": _handle_db_siswa_tool,
                "db_update_tool": _handle_db_update_tool,
                "db_insert_tool": _handle_db_insert_tool,
            }[tool_name]
            return await handler(args, db_pool)
        elif tool_name == "cctv_tool":
            return await _handle_cctv_tool(args)
        elif tool_name == "ss_tool":
            return await _handle_ss_tool(args, client)
            
        return _create_error_response(tool_name, "Tool tidak dikenal.")
    except Exception as e:
        return _create_error_response(tool_name, f"An unexpected error occurred while handling tool call: {e}")
