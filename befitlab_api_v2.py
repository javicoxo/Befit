from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from datetime import date, datetime
from typing import Dict, Any, List, Optional
import os
import math
import random
import requests
import pandas as pd

app = FastAPI()

CSV_PATH = "Base de datos Mercadona definitiva - Base de datos Mercadona definitiva_enriquecida.csv"

# Targets (ya con -200 kcal aplicado, manteniendo proporción; aquí se usan los valores que tú validaste)
TRAIN_TARGET = {"kcal": 2300.0, "protein": 154.0, "carbs": 278.0, "fat": 64.0}
REST_TARGET  = {"kcal": 1900.0, "protein": 151.0, "carbs": 157.0, "fat": 74.0}

MEALS = [
    "desayuno",
    "media_mañana",
    "almuerzo",
    "merienda",
    "cena",
    "postre_almuerzo",
    "postre_cena",
]

MEAL_LABEL = {
    "desayuno": "Desayuno",
    "media_mañana": "Media mañana",
    "almuerzo": "Almuerzo",
    "merienda": "Merienda",
    "cena": "Cena",
    "postre_almuerzo": "Postre (almuerzo)",
    "postre_cena": "Postre (cena)",
}

MEAL_WEIGHTS = {
    "desayuno": 0.22,
    "media_mañana": 0.10,
    "almuerzo": 0.28,
    "merienda": 0.10,
    "cena": 0.25,
    "postre_almuerzo": 0.025,
    "postre_cena": 0.025,
}

# =========================
# In-memory "DB"
# =========================
foods_master: Dict[str, dict] = {}      # id -> food
foods_custom: Dict[str, dict] = {}      # id -> food

days: Dict[str, dict] = {}              # day_date -> day_state
meals_by_day: Dict[str, List[dict]] = {}# day_date -> meals list
meal_items: Dict[int, dict] = {}        # item_id -> item
pantry: Dict[int, dict] = {}            # pantry_id -> pantry item
shopping: Dict[int, dict] = {}          # shopping_id -> item
learning_events: List[dict] = []

_next_meal_id = 1
_next_item_id = 1
_next_pantry_id = 1
_next_shop_id = 1
_next_custom_id = 1

# =========================
# DataFrame global de alimentos (CRÍTICO)
# =========================

foods_df = None

def load_foods_df():
    global foods_df
    if foods_df is not None:
        return foods_df

    df = pd.read_csv(CSV_PATH)

    # Seguridad: columnas obligatorias
    for col in [
        "id",
        "nombre",
        "rol_principal",
        "permitido_comidas",
        "kcal_100g",
        "proteina_100g",
        "hidratos_100g",
        "grasas_100g",
    ]:
        if col not in df.columns:
            df[col] = ""

    foods_df = df
    return foods_df


# =========================
# Models
# =========================
class TrainingBody(BaseModel):
    is_training: bool

class ScanBody(BaseModel):
    ean: str
    status: str = "available"

class PantryUpsertBody(BaseModel):
    food_id: str
    status: str
    qty: float = 1.0
    unit: str = "unit"

class ShoppingAddBody(BaseModel):
    food_id: str
    qty: float = 1.0
    unit: str = "unit"

class ManualFoodBody(BaseModel):
    nombre: str
    marca: Optional[str] = None
    kcal_100g: float
    proteina_100g: float
    hidratos_100g: float
    grasas_100g: float
    permitido_comidas: str
    grupo_mediterraneo: str
    frecuencia_mediterranea: str
    categorias: str
    validated: bool = True

class GenerateDayBody(BaseModel):
    day_date: str

class RegenMealBody(BaseModel):
    meal_id: int

class SwapItemBody(BaseModel):
    meal_item_id: int
    role: str

class AddExtraBody(BaseModel):
    meal_id: int
    food_id: str
    grams: float
    as_treat: bool = True

class ConfirmItemBody(BaseModel):
    consumed_g: float
    is_confirmed: bool

# =========================
# Helpers
# =========================
def macro_dict():
    return {"kcal": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def day_target(is_training: bool) -> dict:
    return TRAIN_TARGET if is_training else REST_TARGET

def food_macros_for_grams(food: dict, grams: float) -> dict:
    g = grams / 100.0
    return {
        "kcal": float(food.get("kcal_100g", 0.0)) * g,
        "protein": float(food.get("proteina_100g", 0.0)) * g,
        "carbs": float(food.get("hidratos_100g", 0.0)) * g,
        "fat": float(food.get("grasas_100g", 0.0)) * g,
    }

def add_macros(a: dict, b: dict) -> dict:
    return {k: float(a.get(k, 0.0)) + float(b.get(k, 0.0)) for k in ["kcal","protein","carbs","fat"]}

def sum_items_macros(items: List[dict], key_grams: str) -> dict:
    total = macro_dict()
    for it in items:
        f = it["food"]
        grams = float(it.get(key_grams, 0.0))
        total = add_macros(total, food_macros_for_grams(f, grams))
    return total

def compute_role(food: dict) -> str:
    return str(food.get("rol_principal") or "hidrato")

def meal_key_from_label(name: str) -> str:
    n = name.lower()
    if "postre" in n and "almuerzo" in n:
        return "postre_almuerzo"
    if "postre" in n and "cena" in n:
        return "postre_cena"
    if "desayuno" in n:
        return "desayuno"
    if "media" in n:
        return "media_mañana"
    if "almuerzo" in n:
        return "almuerzo"
    if "merienda" in n:
        return "merienda"
    if "cena" in n:
        return "cena"
    return "almuerzo"

def normalize_allowed(s: str) -> List[str]:
    if not s:
        return []
    parts = [p.strip().lower() for p in str(s).replace(";", ",").split(",")]
    return [p for p in parts if p]

def pantry_status_for_food(food_id: str) -> str:
    # prioridad: si está en despensa disponible => available; si está out => out; si no existe => missing
    for p in pantry.values():
        if p["food"]["id"] == food_id:
            return p["status"]
    return "missing"

def ensure_day(day_date: str) -> dict:
    if day_date not in days:
        days[day_date] = {
            "day_date": day_date,
            "is_training": True,
            "planned": macro_dict(),
            "adjusted": macro_dict(),
            "consumed": macro_dict(),
        }
    if day_date not in meals_by_day:
        create_empty_meals(day_date)
    return days[day_date]

def create_empty_meals(day_date: str):
    global _next_meal_id
    meals = []
    for k in MEALS:
        meals.append({
            "id": _next_meal_id,
            "day_date": day_date,
            "key": k,
            "name": MEAL_LABEL[k],
            "planned_macros": macro_dict(),
            "adjusted_macros": macro_dict(),
            "items": [],
        })
        _next_meal_id += 1
    meals_by_day[day_date] = meals

def get_food(food_id: str) -> dict:
    if food_id in foods_master:
        return foods_master[food_id]
    if food_id in foods_custom:
        return foods_custom[food_id]
    raise HTTPException(404, f"Food not found: {food_id}")

def load_master():
    if foods_master:
        return
    if not os.path.exists(CSV_PATH):
        raise HTTPException(500, f"CSV no encontrado: {CSV_PATH}")

    df = pd.read_csv(CSV_PATH)
    # columnas cerradas por ti; usamos esas
    for _, r in df.iterrows():
        nombre = r.get("nombre")
        if not isinstance(nombre, str) or not nombre.strip():
            continue
        ean = r.get("ean")
        ean_s = None if pd.isna(ean) else str(int(ean)) if str(ean).replace(".0","").isdigit() else str(ean)
        fid = f"ean:{ean_s}" if ean_s else f"fresh:{nombre.strip().lower()}"
        foods_master[fid] = {
            "id": fid,
            "name": nombre.strip(),
            "ean": ean_s,
            "brand": None if pd.isna(r.get("marca")) else str(r.get("marca")),
            "kcal_100g": float(r.get("kcal_100g") or 0.0),
            "proteina_100g": float(r.get("proteina_100g") or 0.0),
            "hidratos_100g": float(r.get("hidratos_100g") or 0.0),
            "grasas_100g": float(r.get("grasas_100g") or 0.0),
            "rol_principal": str(r.get("rol_principal") or ""),
            "grupo_mediterraneo": str(r.get("grupo_mediterraneo") or ""),
            "frecuencia_mediterranea": str(r.get("frecuencia_mediterranea") or ""),
            "permitido_comidas": str(r.get("permitido_comidas") or ""),
            "categorias": str(r.get("categorias") or ""),
        }

def search_foods(q: str, limit: int) -> List[dict]:
    load_master()
    q = (q or "").strip().lower()
    out = []
    if not q:
        return out
    for f in list(foods_custom.values()) + list(foods_master.values()):
        if q in f["name"].lower() or (f.get("ean") and q in str(f["ean"])):
            out.append({
                "id": f["id"],
                "name": f["name"],
                "ean": f.get("ean"),
                "brand": f.get("brand"),
                "rol_principal": f.get("rol_principal"),
                "permitido_comidas": f.get("permitido_comidas"),
                "grupo_mediterraneo": f.get("grupo_mediterraneo"),
                "frecuencia_mediterranea": f.get("frecuencia_mediterranea"),
                "categorias": f.get("categorias"),
            })
            if len(out) >= limit:
                break
    return out

def candidate_pool_for(meal_key: str, role: str) -> List[dict]:
    load_master()
    role_l = role.lower()
    pool = []
    for f in list(foods_custom.values()) + list(foods_master.values()):
        r = (f.get("rol_principal") or "").lower()
        if role_l and role_l not in r:
            continue
        allowed = normalize_allowed(f.get("permitido_comidas") or "")
        # si no está definido permitido_comidas, lo dejamos pasar (para no bloquear)
        if allowed and meal_key not in allowed and meal_key.replace("_", "") not in "".join(allowed):
            continue
        pool.append(f)
    return pool

def pick_food(meal_key: str, role: str):
    """
    Selecciona un alimento respetando:
    - rol_principal
    - permitido_comidas (CRÍTICO)
    """

    df = load_foods_df().copy()


    # Seguridad
    df["rol_principal"] = df["rol_principal"].fillna("")
    df["permitido_comidas"] = df["permitido_comidas"].fillna("")

    # Filtrar por rol nutricional
    df = df[df["rol_principal"].str.contains(role, case=False)]

    # Filtrar por comida permitida
    df = df[df["permitido_comidas"].str.contains(meal_key, case=False)]

    if df.empty:
        # fallback MUY controlado (último recurso)
        df = foods_df[
            foods_df["rol_principal"]
            .fillna("")
            .str.contains(role, case=False)
        ]

    # Mezclar (priorización de despensa se afinará luego)
    df = df.sample(frac=1)

    food = df.iloc[0]

    return {
        "id": food["id"],
        "name": food["nombre"],

        # kcal
        "kcal_100g": float(food["kcal_100g"]),
        "kcal": float(food["kcal_100g"]),

        # proteínas
        "protein_100g": float(food["proteina_100g"]),
        "proteina_100g": float(food["proteina_100g"]),

        # hidratos
        "carbs_100g": float(food["hidratos_100g"]),
        "hidratos_100g": float(food["hidratos_100g"]),

        # grasas
        "fat_100g": float(food["grasas_100g"]),
        "grasas_100g": float(food["grasas_100g"]),

        # metadatos
        "rol_principal": str(food.get("rol_principal", "")),
        "permitido_comidas": str(food.get("permitido_comidas", "")),
    }

def grams_for_role(food: dict, role: str, target_macros: dict) -> float:
    # grams para aproximar macros del rol (simple y robusto)
    r = role.lower()
    if "proteina" in r:
        base = float(food.get("proteina_100g", 0.0))
        goal = float(target_macros["protein"])
    elif "grasa" in r:
        base = float(food.get("grasas_100g", 0.0))
        goal = float(target_macros["fat"])
    else:
        base = float(food.get("hidratos_100g", 0.0))
        goal = float(target_macros["carbs"])

    if base <= 0.0:
        # fallback por kcal
        kcal100 = float(food.get("kcal_100g", 0.0))
        if kcal100 <= 0:
            return 50.0
        # kcal objetivo aproximado para esa pieza
        kcal_goal = float(target_macros["kcal"])
        g = (kcal_goal / kcal100) * 100.0
        return clamp(g, 10.0, 400.0)

    g = (goal / base) * 100.0
    return clamp(g, 10.0, 400.0)

def meal_targets(day_t: dict, meal_key: str) -> dict:
    w = MEAL_WEIGHTS.get(meal_key, 0.15)
    return {
        "kcal": day_t["kcal"] * w,
        "protein": day_t["protein"] * w,
        "carbs": day_t["carbs"] * w,
        "fat": day_t["fat"] * w,
    }

def recompute_day(day_date: str):
    d = days[day_date]
    meals = meals_by_day[day_date]

    planned = macro_dict()
    adjusted = macro_dict()
    consumed = macro_dict()

    for m in meals:
        planned_m = sum_items_macros(m["items"], "planned_g")
        adjusted_m = sum_items_macros(m["items"], "adjusted_g")
        # consumido: si confirmado usa consumed_g, si no, 0 (solo cuenta confirmado)
        conf_items = []
        for it in m["items"]:
            if it.get("is_confirmed"):
                conf_items.append({**it, "planned_g": it.get("consumed_g", 0.0)})
        consumed_m = sum_items_macros(conf_items, "planned_g")

        m["planned_macros"] = planned_m
        m["adjusted_macros"] = adjusted_m

        planned = add_macros(planned, planned_m)
        adjusted = add_macros(adjusted, adjusted_m)
        consumed = add_macros(consumed, consumed_m)

    d["planned"] = planned
    d["adjusted"] = adjusted
    d["consumed"] = consumed

def ensure_shopping_for_item(food_id: str):
    # si pantry != available, se mete a compra pending (si no existe ya)
    stt = pantry_status_for_food(food_id)
    if stt == "available":
        return
    for it in shopping.values():
        if it["food"]["id"] == food_id and it["status"] == "pending":
            return
    global _next_shop_id
    f = get_food(food_id)
    shopping[_next_shop_id] = {
        "id": _next_shop_id,
        "food": {"id": f["id"], "name": f["name"]},
        "qty": 1.0,
        "unit": "unit",
        "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
    }
    _next_shop_id += 1

def recalc_adjusted_keep_targets(day_date: str):
    # Recalcula adjusted_g para mantener objetivos kcal del día (simple y estable)
    d = days[day_date]
    is_training = d["is_training"]
    tgt = day_target(is_training)

    meals = meals_by_day[day_date]
    # kcal de treats (se mantiene)
    treat_kcal = 0.0
    non_treat_kcal = 0.0
    for m in meals:
        for it in m["items"]:
            kcal = food_macros_for_grams(it["food"], it["planned_g"])["kcal"]
            if it.get("is_treat"):
                treat_kcal += kcal
            else:
                non_treat_kcal += kcal

    remaining = max(0.0, tgt["kcal"] - treat_kcal)
    scale = 1.0
    if non_treat_kcal > 1e-6:
        scale = remaining / non_treat_kcal

    for m in meals:
        for it in m["items"]:
            if it.get("is_treat"):
                it["adjusted_g"] = it["planned_g"]
            else:
                it["adjusted_g"] = clamp(it["planned_g"] * scale, 0.0, 9999.0)

    # shopping autogenerada
    for m in meals:
        for it in m["items"]:
            ensure_shopping_for_item(it["food"]["id"])

    recompute_day(day_date)

# =========================
# API
# =========================
@app.get("/health")
def health():
    return {
        "ok": True,
        "foods_master": len(foods_master),
        "foods_custom": len(foods_custom),
        "days": len(days),
        "pantry": len(pantry),
        "shopping": len(shopping),
        "items": len(meal_items),
    }

@app.get("/foods")
def foods(q: str = "", limit: int = 50):
    return search_foods(q, int(limit))

@app.get("/day")
def get_day(day_date: date):
    dd = day_date.isoformat()
    d = ensure_day(dd)

    t = day_target(d["is_training"])
    return {
        "day_date": dd,
        "is_training": d["is_training"],
        "target_kcal": t["kcal"],
        "target_protein": t["protein"],
        "target_carbs": t["carbs"],
        "target_fat": t["fat"],
        "planned": d["planned"],
        "adjusted": d["adjusted"],
        "consumed": d["consumed"],
    }

@app.post("/day/training")
def set_training(day_date: date, body: TrainingBody):
    dd = day_date.isoformat()
    d = ensure_day(dd)
    d["is_training"] = bool(body.is_training)
    # Reajusta el día a nuevos targets manteniendo treats
    recalc_adjusted_keep_targets(dd)
    return {"ok": True}

@app.get("/day/meals")
def get_day_meals(day_date: date):
    dd = day_date.isoformat()
    ensure_day(dd)
    return meals_by_day[dd]

# ---------- Pantry ----------
@app.get("/pantry")
def get_pantry():
    # devolver lista con {id, food:{id,name}, status, qty, unit}
    return list(pantry.values())

@app.post("/pantry/upsert")
def pantry_upsert(body: PantryUpsertBody):
    global _next_pantry_id
    f = get_food(body.food_id)

    # si existe ya, actualizar
    for pid, p in pantry.items():
        if p["food"]["id"] == f["id"]:
            p["status"] = body.status
            p["qty"] = float(body.qty)
            p["unit"] = body.unit
            # si está out, añadir compra pending
            ensure_shopping_for_item(f["id"])
            return {"ok": True, "id": pid}

    pid = _next_pantry_id
    pantry[pid] = {
        "id": pid,
        "food": {"id": f["id"], "name": f["name"]},
        "status": body.status,
        "qty": float(body.qty),
        "unit": body.unit,
    }
    _next_pantry_id += 1
    ensure_shopping_for_item(f["id"])
    return {"ok": True, "id": pid}

@app.post("/pantry/scan")
def pantry_scan(body: ScanBody):
    load_master()
    ean = (body.ean or "").strip()
    if not ean:
        raise HTTPException(400, "EAN vacío")

    # buscar en master por ean
    found = None
    for f in foods_master.values():
        if f.get("ean") and str(f["ean"]).strip() == ean:
            found = f
            break

    if found:
        pantry_upsert(PantryUpsertBody(food_id=found["id"], status=body.status, qty=1.0, unit="unit"))
        return {"ok": True, "source": "csv", "food_id": found["id"]}

    # si no existe, intentamos OpenFoodFacts (si falla, error)
    try:
        url = f"https://world.openfoodfacts.org/api/v2/product/{ean}.json"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        if not data.get("product"):
            raise HTTPException(404, "No encontrado en OpenFoodFacts")

        prod = data["product"]
        name = prod.get("product_name") or prod.get("generic_name") or f"Producto {ean}"
        brand = None
        if isinstance(prod.get("brands"), str) and prod.get("brands").strip():
            brand = prod.get("brands").split(",")[0].strip()

        nutr = prod.get("nutriments", {}) or {}
        kcal_100g = float(nutr.get("energy-kcal_100g") or 0.0)
        p100 = float(nutr.get("proteins_100g") or 0.0)
        c100 = float(nutr.get("carbohydrates_100g") or 0.0)
        f100 = float(nutr.get("fat_100g") or 0.0)

        # crear custom
        global _next_custom_id
        cid = f"custom:{_next_custom_id}"
        _next_custom_id += 1
        foods_custom[cid] = {
            "id": cid,
            "name": str(name).strip(),
            "ean": ean,
            "brand": brand,
            "kcal_100g": kcal_100g,
            "proteina_100g": p100,
            "hidratos_100g": c100,
            "grasas_100g": f100,
            "rol_principal": infer_role(p100, c100, f100),
            "grupo_mediterraneo": "otros",
            "frecuencia_mediterranea": "ocasional",
            "permitido_comidas": "desayuno,media_mañana,almuerzo,merienda,cena,postre",
            "categorias": "personalizado",
        }

        pantry_upsert(PantryUpsertBody(food_id=cid, status=body.status, qty=1.0, unit="unit"))
        return {"ok": True, "source": "openfoodfacts", "food_id": cid}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"OpenFoodFacts fallo: {e}")

def infer_role(p, c, g) -> str:
    # regla simple basada en dominante (tu base real ya trae rol_principal; esto es solo para custom)
    arr = [("proteina", float(p)), ("hidrato", float(c)), ("grasa", float(g))]
    arr.sort(key=lambda x: x[1], reverse=True)
    return arr[0][0]

# ---------- Shopping ----------
@app.get("/shopping")
def get_shopping(status: str = Query("pending")):
    return [it for it in shopping.values() if it["status"] == status]

@app.post("/shopping/add")
def shopping_add(body: ShoppingAddBody):
    global _next_shop_id
    f = get_food(body.food_id)

    # si ya existe pending, acumula qty
    for it in shopping.values():
        if it["food"]["id"] == f["id"] and it["status"] == "pending":
            it["qty"] = float(it["qty"]) + float(body.qty)
            it["unit"] = body.unit
            return {"ok": True, "id": it["id"]}

    sid = _next_shop_id
    shopping[sid] = {
        "id": sid,
        "food": {"id": f["id"], "name": f["name"]},
        "qty": float(body.qty),
        "unit": body.unit,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
    }
    _next_shop_id += 1
    return {"ok": True, "id": sid}

@app.post("/shopping/mark_bought")
def shopping_mark_bought(item_id: int = Query(...)):
    if item_id not in shopping:
        raise HTTPException(404, "Item no existe")
    shopping[item_id]["status"] = "bought"
    return {"ok": True}

# ---------- Custom foods manual ----------
@app.post("/custom_foods/manual")
def custom_food_manual(body: ManualFoodBody):
    global _next_custom_id
    cid = f"custom:{_next_custom_id}"
    _next_custom_id += 1

    role = infer_role(body.proteina_100g, body.hidratos_100g, body.grasas_100g)

    foods_custom[cid] = {
        "id": cid,
        "name": body.nombre.strip(),
        "ean": None,
        "brand": body.marca,
        "kcal_100g": float(body.kcal_100g),
        "proteina_100g": float(body.proteina_100g),
        "hidratos_100g": float(body.hidratos_100g),
        "grasas_100g": float(body.grasas_100g),
        "rol_principal": role,
        "grupo_mediterraneo": body.grupo_mediterraneo,
        "frecuencia_mediterranea": body.frecuencia_mediterranea,
        "permitido_comidas": body.permitido_comidas,
        "categorias": body.categorias,
    }
    return {"id": cid, "name": foods_custom[cid]["name"]}

# ======================
# Generator
# ======================

@app.post("/generator/generate_day")
def generate_day(body: dict):
    # body puede venir como {"day_date": "YYYY-MM-DD"}
    dd = body.get("day_date")

    if not dd:
        raise HTTPException(status_code=400, detail="day_date missing")

    ensure_day(dd)
    day = days[dd]

    t = day_target(day["is_training"])

    # limpiar items previos del día
    for m in meals_by_day[dd]:
        m["items"] = []

    global _next_item_id

    for m in meals_by_day[dd]:
        mk = m["key"]
        mt = meal_targets(t, mk)

        if mk.startswith("postre"):
            roles = ["hidrato", "grasa"]
        else:
            roles = ["proteina", "hidrato", "grasa"]

        for role in roles:
            f = pick_food(mk, role)
            grams = grams_for_role(f, role, mt)

            item = {
                "id": _next_item_id,
                "meal_id": m["id"],
                "food": {"id": f["id"], "name": f["name"]},
                "role": role,
                "planned_g": float(grams),
                "adjusted_g": float(grams),
                "consumed_g": 0.0,
                "is_confirmed": False,
                "is_extra": False,
                "is_treat": False,
                "pantry_status": pantry_status_for_food(f["id"]),
            }

            meal_items[_next_item_id] = item
            m["items"].append(item)
            _next_item_id += 1

            ensure_shopping_for_item(f["id"])

    recalc_adjusted_keep_targets(dd)
    return {"ok": True}

@app.post("/generator/accept_day")
def accept_day(day_date: date):
    dd = day_date.isoformat()
    ensure_day(dd)
    learning_events.append({"ts": datetime.utcnow().isoformat(), "type": "accept_day", "day_date": dd})
    return {"ok": True}

@app.post("/generator/reject_day")
def reject_day(day_date: date):
    dd = day_date.isoformat()
    ensure_day(dd)
    learning_events.append({"ts": datetime.utcnow().isoformat(), "type": "reject_day", "day_date": dd})
    # regenerar inmediatamente
    generate_day(GenerateDayBody(day_date=dd))
    return {"ok": True}

@app.post("/generator/regenerate_meal")
def regenerate_meal(body: RegenMealBody):
    # encuentra el meal y su day
    target_meal = None
    dd = None
    for day_date, meals in meals_by_day.items():
        for m in meals:
            if m["id"] == body.meal_id:
                target_meal = m
                dd = day_date
                break
        if target_meal:
            break
    if not target_meal:
        raise HTTPException(404, "Meal no encontrado")

    d = ensure_day(dd)
    t = day_target(d["is_training"])
    mk = target_meal["key"]
    mt = meal_targets(t, mk)

    target_meal["items"] = []
    global _next_item_id

    roles = ["hidrato", "grasa"] if mk.startswith("postre") else ["proteina", "hidrato", "grasa"]
    for role in roles:
        f = pick_food(mk, role)
        grams = grams_for_role(f, role, mt)
        it_id = _next_item_id
        _next_item_id += 1
        item = {
            "id": it_id,
            "meal_id": target_meal["id"],
            "food": {"id": f["id"], "name": f["name"]},
            "role": compute_role(f),
            "planned_g": float(grams),
            "adjusted_g": float(grams),
            "consumed_g": 0.0,
            "is_confirmed": False,
            "is_extra": False,
            "is_treat": False,
            "pantry_status": pantry_status_for_food(f["id"]),
        }
        meal_items[it_id] = item
        target_meal["items"].append(item)
        ensure_shopping_for_item(f["id"])

    recalc_adjusted_keep_targets(dd)
    learning_events.append({"ts": datetime.utcnow().isoformat(), "type": "regenerate_meal", "meal_id": target_meal["id"]})
    return {"ok": True}

@app.post("/generator/swap_item")
def swap_item(body: SwapItemBody):
    if body.meal_item_id not in meal_items:
        raise HTTPException(404, "Item no encontrado")

    it = meal_items[body.meal_item_id]
    meal_id = it["meal_id"]

    # localizar meal y day_date
    target_meal = None
    dd = None
    for day_date, meals in meals_by_day.items():
        for m in meals:
            if m["id"] == meal_id:
                target_meal = m
                dd = day_date
                break
        if target_meal:
            break

    if not target_meal:
        raise HTTPException(404, "Meal no encontrado")

    mk = target_meal["key"]
    f = pick_food(mk, body.role)
    old_planned = float(it["planned_g"])

    it["food"] = {"id": f["id"], "name": f["name"]}
    it["role"] = compute_role(f)
    it["planned_g"] = old_planned
    it["adjusted_g"] = old_planned
    it["pantry_status"] = pantry_status_for_food(f["id"])
    ensure_shopping_for_item(f["id"])

    recalc_adjusted_keep_targets(dd)
    learning_events.append({"ts": datetime.utcnow().isoformat(), "type": "swap_item", "item_id": it["id"]})
    return {"ok": True}

# ---------- Consumption ----------
@app.post("/consumption/add_extra")
def add_extra(body: AddExtraBody):
    # encontrar meal y day
    target_meal = None
    dd = None
    for day_date, meals in meals_by_day.items():
        for m in meals:
            if m["id"] == body.meal_id:
                target_meal = m
                dd = day_date
                break
        if target_meal:
            break
    if not target_meal:
        raise HTTPException(404, "Meal no encontrado")

    f = get_food(body.food_id)

    global _next_item_id
    it_id = _next_item_id
    _next_item_id += 1

    item = {
        "id": it_id,
        "meal_id": target_meal["id"],
        "food": {"id": f["id"], "name": f["name"]},
        "role": compute_role(f),
        "planned_g": float(body.grams),
        "adjusted_g": float(body.grams),
        "consumed_g": float(body.grams) if body.as_treat else 0.0,
        "is_confirmed": bool(body.as_treat),
        "is_extra": True,
        "is_treat": bool(body.as_treat),
        "pantry_status": pantry_status_for_food(f["id"]),
    }
    meal_items[it_id] = item
    target_meal["items"].append(item)

    ensure_shopping_for_item(f["id"])
    recalc_adjusted_keep_targets(dd)
    learning_events.append({"ts": datetime.utcnow().isoformat(), "type": "add_extra", "item_id": it_id})
    return {"ok": True}

@app.post("/consumption/confirm_item")
def confirm_item(meal_item_id: int = Query(...), body: ConfirmItemBody = None):
    if meal_item_id not in meal_items:
        raise HTTPException(404, "Item no encontrado")
    it = meal_items[meal_item_id]
    it["consumed_g"] = float(body.consumed_g)
    it["is_confirmed"] = bool(body.is_confirmed)

    # localizar day
    dd = None
    for day_date, meals in meals_by_day.items():
        for m in meals:
            if m["id"] == it["meal_id"]:
                dd = day_date
                break
        if dd:
            break
    if not dd:
        raise HTTPException(404, "Día no encontrado")

    recompute_day(dd)
    learning_events.append({"ts": datetime.utcnow().isoformat(), "type": "confirm_item", "item_id": it["id"]})
    return {"ok": True}
