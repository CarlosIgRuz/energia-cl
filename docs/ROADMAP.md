# Hoja de ruta y bitácora

> Cada sesión (desde el PC o el celular) empieza leyendo este archivo y termina actualizándolo.
> Para retomar, basta decirle al agente: **"continúa con energia-cl"**.

## Pregunta de negocio
**¿Cuál será el costo marginal (CMg) de cada hora de mañana en las barras clave del sistema, y en qué horas caerá a cero por exceso solar?**
Quién lo usaría: un operador de baterías o de una planta solar (cuándo cargar, cuándo inyectar), o un gran consumidor que puede mover carga a las horas baratas.
Entregable: cada noche, un pronóstico de 24 horas por barra con intervalos (cuantiles 10–50–90) y una probabilidad de CMg ≈ 0 por hora, publicado y monitoreado contra lo que efectivamente ocurrió.

## Siguiente tarea
0. Decidir cómo obtener el vertimiento mensual (ver `DECISIONS.md`, 2026-10-15): el sitio responde 403 a Actions.
1. Cuando esté el secret `CEN_USER_KEY`: lanzar `ingesta.yml` con `fuentes=sondeo,cmg` y leer `data/logs/sondeo_cen.json` (formato v4, tamaño máximo de página, si existe CMg programado y generación por central). Con eso, afinar `PATRONES_DEFAULT` y `--limit`, y calcular cuántas requests cuesta un día (define el ritmo del backfill).

## Proyecto · Pronóstico del CMg (~3 semanas)
- [x] P1.1 Estructura del repo, `AGENTS.md`, `DECISIONS.md`, ingestas (CMg Coordinador, clima Open-Meteo, vertimiento mensual), sondeo de endpoints, tests y CI
- [ ] P1.2 Secret + sondeo + descarga de prueba; afinar barras y tamaño de página; backfill del CMg desde el 15-jul-2024 (inicio de la metodología actual) al ritmo que permita el límite de la API, y del clima (pocas llamadas)
- [ ] P1.3 Generación por tecnología/central (endpoint v4 si el sondeo lo encuentra; si no, reportes del sitio del Coordinador) — necesaria para explicar, no para pronosticar
- [ ] P1.4 Warehouse dbt-duckdb: staging (coma decimal, hora local → UTC con días de 23/25 h, deduplicación por versión), marts `fct_cmg_horario`, `fct_clima_horario`, `fct_vertimiento_horario`, `dim_barras`
- [ ] P1.5 EDA: estacionalidad diaria/semanal/anual, regímenes (CMg = 0 al mediodía en el norte), desacople norte–centro, relación con radiación y vertimiento. Fijar horizonte, barras y métricas
- [ ] P1.6 Baselines: naïve estacional (misma hora de ayer y de hace 7 días) y CMg programado del Coordinador si está disponible
- [ ] P1.7 Modelos: estadísticos (MSTL/ETS con `statsforecast`) y LightGBM global con lags, calendario y clima pronosticado; cuantiles; backtest con origen móvil; experimentos en MLflow
- [ ] P1.8 Clasificador de probabilidad de CMg ≈ 0 por hora (calibración, Brier, AUC) y su relación con el vertimiento mensual
- [ ] P1.9 Pronóstico nocturno en producción: job que publica el pronóstico de mañana + API FastAPI en Docker
- [ ] P1.10 Monitoreo: error diario real vs. pronóstico, drift de variables con Evidently, alerta si el error supera al baseline varios días seguidos
- [ ] P1.11 Demo pública (GitHub Pages) + README con resultados, fuentes y limitaciones

## Bitácora
- **2026-10-15** — Creado el repo. Fuentes confirmadas: API SIP del Coordinador (v4 `costo-marginal-online/findByDate`, clave gratuita, 60 consultas/hora por defecto, no filtra por barra), Open-Meteo Historical Forecast (sin clave) y reportes mensuales de Reducciones ERV del Coordinador (XLSX, 1–2 meses de rezago; último: agosto 2026). Ingestas `energia.ingest.{cmg,clima,vertimiento,sondeo}` con checkpoint, tope de requests, manejo de 429 por cabeceras y bitácora en `data/logs/corridas.jsonl`. Workflow `ingesta.yml` (07:30 UTC + manual con fuentes y fechas). 12 tests.
- **2026-10-15** — Primera corrida real en Actions: clima OK (13 y 14-oct, 1 llamada, ~1,9 KB/día; radiación máx. ~950 W/m², valores coherentes). Vertimiento: HTTP 403 del sitio del Coordinador → fuera del cron hasta decidir. CMg y sondeo esperan el secret `CEN_USER_KEY`.
