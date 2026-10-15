# energia-cl · Pronóstico del costo marginal eléctrico en Chile

Proyecto de series de tiempo end-to-end sobre el Sistema Eléctrico Nacional (SEN): ingesta automática diaria,
warehouse en DuckDB + dbt, modelos de pronóstico comparados contra baselines con validación temporal,
despliegue y monitoreo.

**Pregunta:** ¿cuál será el costo marginal de cada hora de mañana en las barras clave del sistema, y en qué horas
caerá a cero por exceso de generación solar?

> 🚧 En construcción. Estado y plan en [`docs/ROADMAP.md`](docs/ROADMAP.md); decisiones en [`DECISIONS.md`](DECISIONS.md).

## Fuentes
| Dato | Fuente | Acceso |
|---|---|---|
| Costo marginal horario por barra | [Coordinador Eléctrico Nacional](https://www.coordinador.cl) — API SIP | Clave gratuita ([portal](https://portal.api.coordinador.cl)) |
| Vertimiento (reducciones ERV) por central y hora | [Coordinador Eléctrico Nacional](https://www.coordinador.cl/operacion/documentos/reducciones-de-generacion-renovable/) | XLSX mensual público |
| Radiación, temperatura, nubosidad, viento | [Open-Meteo.com](https://open-meteo.com) (CC BY 4.0) | Sin clave, uso no comercial |

Fuente: Coordinador Eléctrico Nacional. Datos meteorológicos: Open-Meteo.com (CC BY 4.0).

## Cómo corre
- `.github/workflows/ingesta.yml`: cada noche (07:30 UTC) descarga el día anterior y lo guarda comprimido en `data/raw/`; también se puede ejecutar a mano con fechas para backfill.
- La clave del Coordinador vive solo como secret del repo (`CEN_USER_KEY`).
- `pytest -q` corre los tests (CI en cada push).

Proyecto desarrollado con agentes de IA bajo criterio y revisión propios (ver `AGENTS.md`).
