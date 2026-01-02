"""
BeFitLab — Frontend (Streamlit)

Run:
  pip install streamlit requests
  streamlit run befitlab_ui_v2.py

Backend must be running:
  uvicorn befitlab_api_v2:app --reload --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Optional

import requests
import streamlit as st

API_BASE = "http://127.0.0.1:8000"


def api_get(path: str, params: Optional[dict] = None):
    r = requests.get(f"{API_BASE}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def api_post(path: str, params: Optional[dict] = None, json: Optional[dict] = None):
    r = requests.post(f"{API_BASE}{path}", params=params, json=json, timeout=30)
    r.raise_for_status()
    return r.json()


def pct(value: float, target: float) -> float:
    if target <= 0:
        return 0.0
    return (value / target) * 100.0


def ring(label: str, value: float, target: float):
    p = pct(value, target)
    st.metric(label, f"{value:.0f} / {target:.0f}", f"{p:.0f}%")


def ensure_state():
    if "screen" not in st.session_state:
        st.session_state.screen = "Calendario"
    if "active_date" not in st.session_state:
        st.session_state.active_date = date.today()
    if "cal_year" not in st.session_state:
        st.session_state.cal_year = date.today().year
    if "cal_month" not in st.session_state:
        st.session_state.cal_month = date.today().month


def bottom_nav():
    st.markdown("---")
    cols = st.columns(6)
    labels = ["Calendario", "Día", "Despensa", "Compra", "Estadísticas", "Alimentos"]
    for i, lab in enumerate(labels):
        if cols[i].button(lab, use_container_width=True):
            st.session_state.screen = lab


def header(title: str):
    st.title(title)
    st.caption(f"API: {API_BASE}")


def calendar_view():
    header("🗓️ Calendario")

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("◀ Mes anterior", use_container_width=True):
            y, m = st.session_state.cal_year, st.session_state.cal_month
            if m == 1:
                y -= 1
                m = 12
            else:
                m -= 1
            st.session_state.cal_year, st.session_state.cal_month = y, m
    with col2:
        if st.button("Mes siguiente ▶", use_container_width=True):
            y, m = st.session_state.cal_year, st.session_state.cal_month
            if m == 12:
                y += 1
                m = 1
            else:
                m += 1
            st.session_state.cal_year, st.session_state.cal_month = y, m
    with col3:
        st.write(f"### {calendar.month_name[st.session_state.cal_month]} {st.session_state.cal_year}")

    year = st.session_state.cal_year
    month = st.session_state.cal_month
    cal = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)

    for week in cal:
        cols = st.columns(7)
        for i, d in enumerate(week):
            with cols[i]:
                in_month = (d.month == month)
                box = st.container(border=True)
                with box:
                    st.markdown(f"**{d.day}**" + ("" if in_month else " ·"))
                    try:
                        day = api_get("/day", params={"day_date": d.isoformat()})
                        is_training = day["is_training"]
                    except Exception:
                        is_training = True

                    tcol1, tcol2 = st.columns([1, 1])
                    with tcol1:
                        new_is_training = st.toggle(
                            "Entreno",
                            value=is_training,
                            key=f"train_{d.isoformat()}",
                            label_visibility="collapsed",
                        )
                    with tcol2:
                        st.caption("💪" if new_is_training else "😌")

                    if new_is_training != is_training:
                        api_post("/day/training", params={"day_date": d.isoformat()}, json={"is_training": new_is_training})

                    try:
                        meals = api_get("/day/meals", params={"day_date": d.isoformat()})
                        lunch = next((m for m in meals if "almuerzo" in m["name"].lower()), None)
                        dinner = next((m for m in meals if "cena" in m["name"].lower()), None)

                        def summarize(meal: dict) -> str:
                            if not meal or not meal["items"]:
                                return "—"
                            items = meal["items"]

                            def prio(it):
                                r = (it["role"] or "").lower()
                                if "proteina" in r:
                                    return 0
                                if "hidrato" in r:
                                    return 1
                                if "grasa" in r:
                                    return 2
                                return 3

                            items_sorted = sorted(items, key=prio)
                            names = [it["food"]["name"] for it in items_sorted[:2]]
                            if len(items_sorted) > 2:
                                return " + ".join(names) + " + otros"
                            return " + ".join(names)

                        st.caption(f"🥗 {summarize(lunch)}")
                        st.caption(f"🌙 {summarize(dinner)}")
                    except Exception:
                        st.caption("🥗 —")
                        st.caption("🌙 —")

                    if st.button("🍽️ Ver día", key=f"open_{d.isoformat()}", use_container_width=True):
                        st.session_state.active_date = d
                        st.session_state.screen = "Día"


def day_view():
    header("🍽️ Día / Comidas")

    d: date = st.session_state.active_date
    day = api_get("/day", params={"day_date": d.isoformat()})
    meals = api_get("/day/meals", params={"day_date": d.isoformat()})
    planned = day.get("planned", {})
    consumed = day.get("consumed", {})

    target_kcal = day.get("target_kcal", 0)
    target_p = day.get("target_protein", 0)
    target_c = day.get("target_carbs", 0)
    target_f = day.get("target_fat", 0)

    plan_kcal = planned.get("kcal", 0)
    plan_p = planned.get("protein", 0)
    plan_c = planned.get("carbs", 0)
    plan_f = planned.get("fat", 0)
 
    cons_kcal = consumed.get("kcal", 0)
    cons_p = consumed.get("protein", 0)
    cons_c = consumed.get("carbs", 0)
    cons_f = consumed.get("fat", 0)


    st.write(f"### 📅 {d.strftime('%A %d/%m/%Y')}")
    st.write("💪 Entreno" if day.get("is_training", False) else "😌 Descanso")


    st.write("#### Objetivos y progreso")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        ring("🔥 Kcal (plan)", day["planned"]["kcal"], day["target_kcal"])
        st.caption(f"Ajustado: {day['adjusted']['kcal']:.0f} · Consumido: {day['consumed']['kcal']:.0f}")
    with c2:
        ring("🥩 Prot (plan)", day["planned"]["protein"], day["target_protein"])
        st.caption(f"Ajustado: {day['adjusted']['protein']:.0f} · Consumido: {day['consumed']['protein']:.0f}")
    with c3:
        ring("🍞 HC (plan)", day["planned"]["carbs"], day["target_carbs"])
        st.caption(f"Ajustado: {day['adjusted']['carbs']:.0f} · Consumido: {day['consumed']['carbs']:.0f}")
    with c4:
        ring("🥑 Gras (plan)", day["planned"]["fat"], day["target_fat"])
        st.caption(f"Ajustado: {day['adjusted']['fat']:.0f} · Consumido: {day['consumed']['fat']:.0f}")

    st.markdown("---")

    st.write("#### 🤖 Generador")
    g1, g2, g3 = st.columns(3)
    with g1:
        if st.button("🔄 Generar menú del día", use_container_width=True):
            api_post("/generator/generate_day", json={"day_date": d.isoformat()})
            st.rerun()
    with g2:
        if st.button("✅ Aceptar menú", use_container_width=True):
            api_post("/generator/accept_day", params={"day_date": d.isoformat()})
            st.success("Menú aceptado.")
    with g3:
        if st.button("❌ Rechazar menú (nuevo)", use_container_width=True):
            api_post("/generator/reject_day", params={"day_date": d.isoformat()})
            st.rerun()

    st.markdown("---")
    st.write("#### Comidas del día")

    for meal in meals:
        with st.container(border=True):
            top = st.columns([3, 1, 1])
            top[0].subheader(meal["name"])
            if top[1].button("🔁 Cambiar comida", key=f"regen_{meal['id']}", use_container_width=True):
                api_post("/generator/regenerate_meal", json={"meal_id": meal["id"]})
                st.rerun()
            if top[2].button("🍬 Añadir golosina", key=f"treat_{meal['id']}", use_container_width=True):
                st.session_state[f"show_treat_{meal['id']}"] = True

            if st.session_state.get(f"show_treat_{meal['id']}", False):
                st.markdown("**Buscar alimento (CSV + personalizados)**")
                q = st.text_input("Buscar", key=f"treat_q_{meal['id']}")
                foods = api_get("/foods", params={"q": q, "limit": 50})
                options = [f"{f['name']} — {f['id']}" for f in foods] or ["(sin resultados)"]
                sel = st.selectbox("Elegir", options, key=f"treat_sel_{meal['id']}")
                grams = st.number_input("Gramos consumidos", min_value=0.0, value=30.0, step=5.0, key=f"treat_g_{meal['id']}")

                cta1, cta2 = st.columns(2)
                if cta1.button("Añadir", key=f"treat_add_{meal['id']}", use_container_width=True):
                    if "—" not in sel:
                        st.warning("Seleccione un alimento válido.")
                    else:
                        food_id = sel.split("—")[-1].strip()
                        api_post("/consumption/add_extra", json={"meal_id": meal["id"], "food_id": food_id, "grams": grams, "as_treat": True})
                        st.session_state[f"show_treat_{meal['id']}"] = False
                        st.rerun()
                if cta2.button("Cancelar", key=f"treat_cancel_{meal['id']}", use_container_width=True):
                    st.session_state[f"show_treat_{meal['id']}"] = False
                    st.rerun()

            if not meal["items"]:
                st.caption("— Sin alimentos todavía. Genera o edita esta comida.")
            else:
                for it in meal["items"]:
                    f = it["food"]
                    status = it["pantry_status"]
                    left, mid, right = st.columns([6, 2, 2])

                    planned = it["planned_g"]
                    adjusted = it["adjusted_g"]
                    label_prefix = "🍬" if it["is_treat"] else "➕" if it["is_extra"] else ""
                    shop_tag = "🛒" if status != "available" else ""

                    left.write(f"{label_prefix} **{f['name']}** {shop_tag}")
                    left.caption(f"Rol: {it['role']} · Despensa: {status}")

                    mid.write(f"Propuesto: **{planned:.0f} g**")
                    mid.write(f"Recalc.: **{adjusted:.0f} g**")

                    if right.button("🔄", key=f"swap_{it['id']}", help="Cambiar este alimento", use_container_width=True):
                        api_post("/generator/swap_item", json={"meal_item_id": it["id"], "role": it["role"]})
                        st.rerun()

            st.caption(
                f"Plan: {meal['planned_macros']['kcal']:.0f} kcal · "
                f"P {meal['planned_macros']['protein']:.0f} · "
                f"HC {meal['planned_macros']['carbs']:.0f} · "
                f"G {meal['planned_macros']['fat']:.0f}"
            )
            st.caption(
                f"Ajustado: {meal['adjusted_macros']['kcal']:.0f} kcal · "
                f"P {meal['adjusted_macros']['protein']:.0f} · "
                f"HC {meal['adjusted_macros']['carbs']:.0f} · "
                f"G {meal['adjusted_macros']['fat']:.0f}"
            )


def pantry_view():
    header("🧺 Despensa")

    tab_scan, tab_list, tab_add = st.tabs(["📷 Escanear EAN", "📦 Mi despensa", "➕ Añadir manual"])

    with tab_scan:
        st.subheader("Escanear / introducir EAN")
        st.caption("Si el EAN está en tu CSV, se añade directamente. Si no, se consulta OpenFoodFacts y se crea como personalizado (pendiente).")
        ean = st.text_input("EAN", value="")
        status = st.selectbox("Estado en despensa", ["available", "out"])
        if st.button("Añadir por EAN", use_container_width=True):
            api_post("/pantry/scan", json={"ean": ean, "status": status})
            st.success("Producto añadido a la despensa.")
            st.rerun()

    with tab_list:
        pantry = api_get("/pantry")
        tab1, tab2 = st.tabs(["🟢 Disponibles", "⚪ Agotados"])

        def render_list(status_value: str):
            items = [p for p in pantry if p["status"] == status_value]
            if not items:
                st.caption("— Sin elementos.")
                return
            for p in sorted(items, key=lambda x: x["food"]["name"].lower()):
                with st.container(border=True):
                    st.write(f"**{p['food']['name']}**")
                    st.caption(f"Cantidad: {p['qty']} {p['unit']} · Ref: {p['food']['id']}")
                    c1, c2 = st.columns(2)
                    if status_value == "available":
                        if c1.button("Marcar agotado", key=f"out_{p['id']}", use_container_width=True):
                            api_post("/pantry/upsert", json={"food_id": p["food"]["id"], "status": "out", "qty": p["qty"], "unit": p["unit"]})
                            st.rerun()
                        if c2.button("Editar cantidad", key=f"edit_{p['id']}", use_container_width=True):
                            st.session_state[f"edit_qty_{p['id']}"] = True
                    else:
                        if c1.button("Reactivar", key=f"avail_{p['id']}", use_container_width=True):
                            api_post("/pantry/upsert", json={"food_id": p["food"]["id"], "status": "available", "qty": p["qty"], "unit": p["unit"]})
                            st.rerun()
                        if c2.button("Añadir a compra", key=f"buy_{p['id']}", use_container_width=True):
                            api_post("/shopping/add", json={"food_id": p["food"]["id"], "qty": 1.0, "unit": "unit"})
                            st.success("Añadido a la lista de la compra.")

                    if st.session_state.get(f"edit_qty_{p['id']}", False):
                        qty = st.number_input("Nueva cantidad", min_value=0.0, value=float(p["qty"]), step=10.0, key=f"qty_{p['id']}")
                        unit = st.text_input("Unidad", value=p["unit"], key=f"unit_{p['id']}")
                        s1, s2 = st.columns(2)
                        if s1.button("Guardar", key=f"save_{p['id']}", use_container_width=True):
                            api_post("/pantry/upsert", json={"food_id": p["food"]["id"], "status": p["status"], "qty": qty, "unit": unit})
                            st.session_state[f"edit_qty_{p['id']}"] = False
                            st.rerun()
                        if s2.button("Cancelar", key=f"cancel_{p['id']}", use_container_width=True):
                            st.session_state[f"edit_qty_{p['id']}"] = False
                            st.rerun()

        with tab1:
            render_list("available")
        with tab2:
            render_list("out")

    with tab_add:
        st.subheader("Añadir alimento personalizado (manual)")
        st.caption("Esto crea un alimento personal y lo normaliza a rol_principal automáticamente.")
        nombre = st.text_input("Nombre")
        marca = st.text_input("Marca (opcional)")
        kcal = st.number_input("kcal/100g", min_value=0.0, value=0.0, step=1.0)
        p = st.number_input("proteína/100g", min_value=0.0, value=0.0, step=0.1)
        c = st.number_input("hidratos/100g", min_value=0.0, value=0.0, step=0.1)
        g = st.number_input("grasas/100g", min_value=0.0, value=0.0, step=0.1)
        permitido = st.text_input("permitido_comidas", value="almuerzo,cena")
        grupo = st.text_input("grupo_mediterraneo", value="otros")
        freq = st.text_input("frecuencia_mediterranea", value="ocasional")
        cats = st.text_input("categorias", value="personalizado")
        if st.button("Crear alimento", use_container_width=True):
            f = api_post("/custom_foods/manual", json={
                "nombre": nombre,
                "marca": marca or None,
                "kcal_100g": kcal,
                "proteina_100g": p,
                "hidratos_100g": c,
                "grasas_100g": g,
                "permitido_comidas": permitido,
                "grupo_mediterraneo": grupo,
                "frecuencia_mediterranea": freq,
                "categorias": cats,
                "validated": True
            })
            st.success(f"Creado: {f['name']} · Ref {f['id']}")


def shopping_view():
    header("🛒 Lista de la compra")

    items = api_get("/shopping", params={"status": "pending"})
    if not items:
        st.caption("— No hay compras pendientes.")
    else:
        for it in items:
            with st.container(border=True):
                st.write(f"**{it['food']['name']}**")
                st.caption(f"{it['qty']} {it['unit']} · Ref: {it['food']['id']}")
                if st.button("✅ Marcar como comprado", key=f"bought_{it['id']}", use_container_width=True):
                    api_post("/shopping/mark_bought", params={"item_id": it["id"]})
                    st.rerun()


def stats_view():
    header("📊 Estadísticas")

    period = st.selectbox("Periodo", ["Últimos 7 días", "Últimos 14 días", "Últimos 30 días", "Mes actual"])
    today = date.today()

    if period == "Últimos 7 días":
        days = [today.fromordinal(today.toordinal() - i) for i in range(6, -1, -1)]
    elif period == "Últimos 14 días":
        days = [today.fromordinal(today.toordinal() - i) for i in range(13, -1, -1)]
    elif period == "Últimos 30 días":
        days = [today.fromordinal(today.toordinal() - i) for i in range(29, -1, -1)]
    else:
        y, m = today.year, today.month
        last_day = calendar.monthrange(y, m)[1]
        days = [date(y, m, d) for d in range(1, last_day + 1)]

    totals = {"kcal": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    targets = {"kcal": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    valid_days = 0

    for d in days:
        try:
            day = api_get("/day", params={"day_date": d.isoformat()})
            totals["kcal"] += day["consumed"]["kcal"]
            totals["protein"] += day["consumed"]["protein"]
            totals["carbs"] += day["consumed"]["carbs"]
            totals["fat"] += day["consumed"]["fat"]
            targets["kcal"] += day["target_kcal"]
            targets["protein"] += day["target_protein"]
            targets["carbs"] += day["target_carbs"]
            targets["fat"] += day["target_fat"]
            valid_days += 1
        except Exception:
            pass

    st.write("### Resumen del periodo (consumo confirmado)")
    if valid_days == 0:
        st.info("No hay datos todavía. Genera menús y confirma consumos.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            ring("🔥 Kcal (media)", totals["kcal"] / valid_days, targets["kcal"] / valid_days)
        with c2:
            ring("🥩 Prot (media)", totals["protein"] / valid_days, targets["protein"] / valid_days)
        with c3:
            ring("🍞 HC (media)", totals["carbs"] / valid_days, targets["carbs"] / valid_days)
        with c4:
            ring("🥑 Gras (media)", totals["fat"] / valid_days, targets["fat"] / valid_days)

    st.markdown("---")
    st.write("### Confirmar lo consumido (por día)")

    sel_day = st.date_input("Selecciona un día", value=st.session_state.active_date)
    day = api_get("/day", params={"day_date": sel_day.isoformat()})
    meals = api_get("/day/meals", params={"day_date": sel_day.isoformat()})

    st.caption("Aquí confirmas lo que comiste realmente. Todo lo generado/modificado aparece aquí.")
    st.write(f"**Objetivos:** {day['target_kcal']:.0f} kcal · P {day['target_protein']:.0f} · HC {day['target_carbs']:.0f} · G {day['target_fat']:.0f}")
    st.write(f"**Consumido:** {day['consumed']['kcal']:.0f} kcal · P {day['consumed']['protein']:.0f} · HC {day['consumed']['carbs']:.0f} · G {day['consumed']['fat']:.0f}")

    for meal in meals:
        with st.container(border=True):
            st.subheader(meal["name"])

            c1, _ = st.columns([1, 2])
            if c1.button("➕ Añadir alimento consumido", key=f"extra_{meal['id']}", use_container_width=True):
                st.session_state[f"show_extra_{meal['id']}"] = True

            if st.session_state.get(f"show_extra_{meal['id']}", False):
                q = st.text_input("Buscar alimento", key=f"extra_q_{meal['id']}")
                foods = api_get("/foods", params={"q": q, "limit": 50})
                options = [f"{f['name']} — {f['id']}" for f in foods] or ["(sin resultados)"]
                sel = st.selectbox("Alimento", options, key=f"extra_sel_{meal['id']}")
                grams = st.number_input("Gramos consumidos", min_value=0.0, value=30.0, step=5.0, key=f"extra_g_{meal['id']}")
                as_treat = st.toggle("Marcar como golosina 🍬", value=True, key=f"extra_treat_{meal['id']}")
                a1, a2 = st.columns(2)
                if a1.button("Añadir", key=f"extra_add_{meal['id']}", use_container_width=True):
                    if "—" not in sel:
                        st.warning("Seleccione un alimento válido.")
                    else:
                        food_id = sel.split("—")[-1].strip()
                        api_post("/consumption/add_extra", json={"meal_id": meal["id"], "food_id": food_id, "grams": grams, "as_treat": bool(as_treat)})
                        st.session_state[f"show_extra_{meal['id']}"] = False
                        st.rerun()
                if a2.button("Cancelar", key=f"extra_cancel_{meal['id']}", use_container_width=True):
                    st.session_state[f"show_extra_{meal['id']}"] = False
                    st.rerun()

            if not meal["items"]:
                st.caption("— Sin items.")
                continue

            for it in meal["items"]:
                f = it["food"]
                label_prefix = "🍬" if it["is_treat"] else "➕" if it["is_extra"] else ""
                st.write(f"{label_prefix} **{f['name']}**  · Propuesto {it['planned_g']:.0f} g · Recalc {it['adjusted_g']:.0f} g")

                cols = st.columns([2, 2, 2, 2])
                consumed = cols[0].number_input(
                    "Consumido (g)",
                    min_value=0.0,
                    value=float(it["consumed_g"] if it["is_confirmed"] else it["planned_g"]),
                    step=5.0,
                    key=f"cons_{it['id']}",
                )
                confirmed = cols[1].toggle("Confirmado", value=bool(it["is_confirmed"]), key=f"conf_{it['id']}")
                if cols[2].button("Guardar", key=f"save_cons_{it['id']}", use_container_width=True):
                    api_post("/consumption/confirm_item", params={"meal_item_id": it["id"]}, json={"consumed_g": consumed, "is_confirmed": confirmed})
                    st.rerun()
                cols[3].caption(f"Rol: {it['role']}")


def foods_view():
    header("🍎 Alimentos (búsqueda)")
    st.caption("Busca en tu CSV maestro y en tus alimentos personalizados.")
    q = st.text_input("Buscar")
    limit = st.slider("Límite", min_value=10, max_value=200, value=50, step=10)
    foods = api_get("/foods", params={"q": q, "limit": limit})
    st.dataframe(foods, use_container_width=True)


def main():
    ensure_state()

    with st.sidebar:
        st.header("⚙️ Info")
        st.caption("BeFitLab · Backend + CSV maestro + despensa prioritaria")
        st.write("Fecha activa")
        st.session_state.active_date = st.date_input("Día", value=st.session_state.active_date)

        if st.button("🩺 Health", use_container_width=True):
            h = api_get("/health")
            st.json(h)

    screen = st.session_state.screen

    if screen == "Calendario":
        calendar_view()
    elif screen == "Día":
        day_view()
    elif screen == "Despensa":
        pantry_view()
    elif screen == "Compra":
        shopping_view()
    elif screen == "Estadísticas":
        stats_view()
    elif screen == "Alimentos":
        foods_view()
    else:
        calendar_view()

    bottom_nav()


if __name__ == "__main__":
    main()
