import asyncio
import os
import tempfile
from typing import Dict

import pyautogui
from google.genai import types

from database import execute_sql_query, save_audit_log, DatabaseError
from utils import _create_error_response

google_search_tool = types.Tool(
    google_search=types.GoogleSearch()
)

db_gukar_tool = types.FunctionDeclaration(
    name="db_gukar_tool",
    description="""
        Tool ini digunakan untuk mencari data guru atau karyawan dari database. Gunakan tool ini HANYA untuk query SELECT. 
        Mendukung pencarian fuzzy (LIKE '%%term%%') pada nama, nip, atau mengajar.
        Jangan pernah tampilkan data Ibu kandung dan NIK guru.
    """,
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "search_term": types.Schema(
                type="STRING",
                description="Nama, NIP, atau mata pelajaran/jabatan yang dicari. Contoh: 'budi', 'guru matematika'",
            ),
            "columns": types.Schema(
                type="ARRAY",
                items={"type": "STRING"},
                description="Daftar kolom yang ingin diambil. Kolom tersedia: nama, gender, nip, tempat_lahir, tanggal_lahir, pendidikan_terakhir, tahun_lulus, bidang_studi, mengajar, agama, no_hp, email, desa, alamat.",
            ),
        },
        required=["search_term"]
    )
)

db_siswa_tool = types.FunctionDeclaration(
    name="db_siswa_tool",
    description="""
        Gunakan tool ini untuk mencari data siswa atau menghitung jumlah siswa berdasarkan nama, NISN, NIPD, atau rombel_saat_ini (kelas).
        Mendukung pencarian fuzzy pada nama. Hasil agregasi (count) bisa diminta.
    """,
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "search_term": types.Schema(
                type="STRING",
                description="Nama, NISN, atau NIPD siswa yang dicari.",
            ),
            "rombel_saat_ini": types.Schema(
                type="STRING",
                description="Nama rombel atau kelas. Contoh: 'X 1'",
            ),
            "aggregate": types.Schema(
                type="STRING",
                description="Jenis agregasi. Hanya mendukung 'count'.",
            ),
        },
        required=[]
    )
)

db_update_tool = types.FunctionDeclaration(
    name="db_update_tool",
    description="Tool ini digunakan untuk mengupdate data di database.",
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "table_name": types.Schema(type="STRING", description="Contoh: 'siswa', 'gukar'"),
            "updates": types.Schema(
                type="OBJECT",
                description="Dictionary kolom dan nilai baru. Contoh: {'no_seri_ijazah': 'ABC12345', 'tahun_lulus': '2023'}",
            ),
            "where_clause": types.Schema(
                type="OBJECT",
                description="Dictionary kolom dan nilai untuk filter WHERE (AND). Contoh: {'nisn': '1234567890'}",
            ),
        },
        required=["table_name", "updates", "where_clause"],
    ),
)

db_insert_tool = types.FunctionDeclaration(
    name="db_insert_tool",
    description="Tool ini digunakan untuk menambahkan data baru ke database.",
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "table_name": types.Schema(type="STRING", description="Contoh: 'siswa', 'gukar'"),
            "data": types.Schema(
                type="OBJECT",
                description="Dictionary kolom dan nilai yang akan dimasukkan.",
            ),
        },
        required=["table_name", "data"],
    )
)

cctv_tool = types.FunctionDeclaration(
    name="cctv_tool",
    description="Gunakan tool ini untuk merestart atau menghentikan cctv.",
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "command": types.Schema(
                type="STRING",
                description="Command untuk cctv: restart atau stop",
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

# --- Column Whitelists ---
GUKAR_ALLOWED_COLS = [
    "nama", "gender", "golongan", "nip", "tempat_lahir", "tanggal_lahir",
    "pendidikan_terakhir", "tahun_lulus", "bidang_studi", "mengajar",
    "agama", "no_hp", "email", "desa", "alamat"
]

SISWA_ALLOWED_COLS = [
    "nama", "jk", "nisn", "nipd", "rombel_saat_ini", "tempat_lahir",
    "tanggal_lahir", "agama", "alamat", "no_hp", "email",
    "no_seri_ijazah", "tahun_lulus", "sekolah_asal"
]

GUKAR_UPDATE_ALLOWED_COLS = [
    "nama", "gender", "golongan", "nip", "tempat_lahir", "tanggal_lahir",
    "pendidikan_terakhir", "tahun_lulus", "bidang_studi", "mengajar",
    "agama", "no_hp", "email", "desa", "alamat"
]

SISWA_UPDATE_ALLOWED_COLS = [
    "nama", "jk", "nisn", "nipd", "rombel_saat_ini", "tempat_lahir",
    "tanggal_lahir", "agama", "alamat", "no_hp", "email",
    "no_seri_ijazah", "tahun_lulus", "sekolah_asal"
]

ALLOWED_COLUMNS = {
    "gukar": {"select": GUKAR_ALLOWED_COLS, "update": GUKAR_UPDATE_ALLOWED_COLS},
    "siswa": {"select": SISWA_ALLOWED_COLS, "update": SISWA_UPDATE_ALLOWED_COLS},
}


async def _handle_db_gukar_tool(args: Dict, db_pool) -> types.Part:
    tool_name = "db_gukar_tool"
    search_term = args.get("search_term")
    cols = args.get("columns", ["nama", "nip", "mengajar"])
    
    safe_cols = [c for c in cols if c in GUKAR_ALLOWED_COLS]
    if not safe_cols:
        safe_cols = ["nama", "nip", "mengajar"]
    
    col_str = ", ".join([f"`{c}`" for c in safe_cols])
    sql_query = f"SELECT {col_str} FROM `gukar` WHERE `nama` LIKE %s OR `nip` = %s OR `mengajar` LIKE %s"
    params = (f"%{search_term}%", search_term, f"%{search_term}%")
    
    try:
        query_result = await execute_sql_query(db_pool, sql_query, params=params)
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
    tool_name = "db_update_tool"
    table_name = args.get("table_name")
    updates = args.get("updates")
    where_clause = args.get("where_clause")

    if not all([table_name, updates, where_clause]):
        return _create_error_response(tool_name, "Missing required arguments")
    
    if table_name not in ALLOWED_COLUMNS:
        return _create_error_response(tool_name, "Table not allowed.")

    # Validate column names against whitelist
    allowed = ALLOWED_COLUMNS[table_name]["update"]
    for col in updates.keys():
        if col not in allowed:
            return _create_error_response(tool_name, f"Column '{col}' is not allowed for update on table '{table_name}'.")
    for col in where_clause.keys():
        if col not in allowed:
            return _create_error_response(tool_name, f"Column '{col}' is not allowed in WHERE clause for table '{table_name}'.")

    set_parts = []
    params = []
    for col, val in updates.items():
        set_parts.append(f"`{col}` = %s")
        params.append(val)
    
    where_parts = []
    for col, val in where_clause.items():
        where_parts.append(f"`{col}` = %s")
        params.append(val)
    
    sql_query = f"UPDATE `{table_name}` SET {', '.join(set_parts)} WHERE {' AND '.join(where_parts)}"
    try:
        query_result = await execute_sql_query(db_pool, sql_query, params=tuple(params))
        # Audit log
        await save_audit_log(db_pool, table_name, "UPDATE", details=f"SET {updates} WHERE {where_clause}")
        return types.Part.from_function_response(
            name=tool_name,
            response={'result': str(query_result)},
        )
    except DatabaseError as e:
        return _create_error_response(tool_name, f"Error executing database operation: {e}")

async def _handle_db_insert_tool(args: Dict, db_pool) -> types.Part:
    tool_name = "db_insert_tool"
    table_name = args.get("table_name")
    data = args.get("data")

    if not all([table_name, data]):
        return _create_error_response(tool_name, "Missing required arguments")
    
    if table_name not in ALLOWED_COLUMNS:
        return _create_error_response(tool_name, "Table not allowed.")

    # Validate column names against whitelist
    allowed = ALLOWED_COLUMNS[table_name]["update"]
    for col in data.keys():
        if col not in allowed:
            return _create_error_response(tool_name, f"Column '{col}' is not allowed for insert on table '{table_name}'.")

    cols = data.keys()
    vals = data.values()
    placeholders = ", ".join(["%s"] * len(cols))
    column_str = ", ".join([f"`{c}`" for c in cols])
    
    sql_query = f"INSERT INTO `{table_name}` ({column_str}) VALUES ({placeholders})"
    try:
        query_result = await execute_sql_query(db_pool, sql_query, params=tuple(vals))
        # Audit log
        await save_audit_log(db_pool, table_name, "INSERT", details=f"DATA {data}")
        return types.Part.from_function_response(
            name=tool_name,
            response={'result': str(query_result)}
        )
    except DatabaseError as e:
        return _create_error_response(tool_name, f"Error executing database operation: {e}")

async def _handle_cctv_tool(args: Dict) -> types.Part:
    """Handles CCTV restart or stop based on the command argument."""
    command = args.get("command", "restart")
    
    if command == "stop":
        pm2_cmd = 'pm2 stop "Super Simpel NVR"'
        success_msg = "Proses 'Super Simpel NVR' berhasil dihentikan."
    else:
        pm2_cmd = 'pm2 restart "Super Simpel NVR"'
        success_msg = "Proses 'Super Simpel NVR' berhasil direstart."
    
    try:
        process = await asyncio.create_subprocess_shell(
            pm2_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            return types.Part.from_function_response(
                name="cctv_tool",
                response={"result": success_msg},
            )
        else:
            error_message = f"Error executing '{command}' on 'Super Simpel NVR': {stderr.decode()}"
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
            name="ss_tool",
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
