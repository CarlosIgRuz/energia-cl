# Instrucciones para agentes en este repo

Al iniciar una sesión, lee primero `docs/ROADMAP.md` (estado actual y siguiente tarea) y `DECISIONS.md`.
Trabaja sobre un clon en la nube; el PC del usuario no es necesario.

## Reglas
- **Secretos:** nunca escribir la clave del Coordinador (`CEN_USER_KEY`) ni otros secretos en código, logs, commits o chats. Vive solo como secret del repo en GitHub; el agente nunca la pide.
- **Red:** la red del agente no llega a sitios del gobierno. Toda descarga corre en GitHub Actions: `cmg.yml` (único workflow que usa la clave del Coordinador; día nuevo + historial, 4×/día) e `ingesta.yml` (fuentes sin clave). Nunca lanzar consultas al Coordinador desde otro workflow mientras `cmg.yml` corre. El agente lanza corridas con `gh workflow run` y lee los resultados en `data/logs/corridas_<fuente>.jsonl` (los logs de Actions no son legibles desde el agente).
- **Condiciones de uso:**
  - API SIP del Coordinador: respetar el límite de la cuenta (límite por volumen, sin cabeceras de reset: ~1 página de 10.000 cada 20 min; páginas desde 0; no filtra por barra). Tope por corrida (`--max-requests`), checkpoint para retomar, nunca eludir el límite ni usar varias claves.
  - Open-Meteo: uso no comercial, < 10.000 llamadas/día; datos CC BY 4.0.
  - Sitio web del Coordinador (vertimiento): pocas requests, con pausa, sin re-descargar archivos existentes.
- **Atribución:** todo lo publicado (README, demo, gráficos) cita "Fuente: Coordinador Eléctrico Nacional" y "Datos meteorológicos: Open-Meteo.com (CC BY 4.0)" según corresponda.
- **Datos crudos** en `data/raw/` comprimidos (`.json.gz`; los XLSX ya vienen comprimidos), nunca se modifican; toda limpieza va en dbt (`dbt/models/staging`).
- **Tiempo:** guardar y razonar en UTC; convertir a hora de Chile solo en staging (cuidado con los cambios de horario: días de 23 y 25 horas).
- **Sin fuga de información:** las variables de un pronóstico solo pueden usar lo conocido al momento de emitirlo (por eso el clima viene de pronósticos históricos y no del reanálisis). Validación siempre temporal (origen móvil), nunca aleatoria.
- **Métricas:** siempre contra baselines (naïve estacional y, si existe, el CMg programado del Coordinador) y con varias métricas (MAE, RMSE, pinball; Brier/AUC para eventos).
- Todo código nuevo lleva al menos un test en `tests/`; `pytest` debe pasar antes de commitear.
- Al terminar una sesión: actualizar la bitácora en `docs/ROADMAP.md` y registrar decisiones en `DECISIONS.md`.
- Commits pequeños, en español, formato `tipo: descripción` (feat, fix, data, docs, test). Autor `CarlosIgRuz <carlosigruz@gmail.com>`, committer Claude.
