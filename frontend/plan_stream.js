/* plan_stream.js — Progressive Loading cho POST /api/plan/calculate (Vanilla JS + Leaflet)
 *
 * Request nên gửi:  { ..., include_ai_explanation: true, ai_delivery: "stream", route_wait_ms: 250,
 *                     polyline_format: "encoded", simplify_epsilon_m: 5 }
 * DOM: thêm data-advisory-id="hotel_tradeoff" / "roadtrip_tradeoff" vào phần tử hiển thị lời khuyên.
 * Dùng:  const stop = startPlanStream(plan, map);   // stop() để huỷ khi người dùng tính lại kế hoạch
 */
const DAY_COLORS = ['#e63946', '#2a9d8f', '#f4a261', '#457b9d', '#9b5de5', '#06d6a0', '#ef476f'];
const dayLayers = new Map();                       // day (1-based) -> L.Polyline

function decodePolyline(str) {                     // polyline5 (Google) -> [[lat, lng], ...]
  const out = []; let i = 0, lat = 0, lng = 0;
  while (i < str.length) {
    for (const isLng of [false, true]) {
      let shift = 0, result = 0, b;
      do { b = str.charCodeAt(i++) - 63; result |= (b & 31) << shift; shift += 5; } while (b >= 32);
      const delta = (result & 1) ? ~(result >> 1) : (result >> 1);
      if (isLng) lng += delta; else lat += delta;
    }
    out.push([lat / 1e5, lng / 1e5]);
  }
  return out;
}

function drawDayRoute(map, d) {                    // d = data của event day_route
  const latlngs = typeof d.points === 'string' ? decodePolyline(d.points) : d.points;
  if (!latlngs || !latlngs.length) return;
  const style = { color: DAY_COLORS[(d.day - 1) % DAY_COLORS.length], weight: 5, opacity: 0.85,
                  dashArray: d.status === 'degraded' ? '8 8' : null };   // degraded = đường ước lượng -> nét đứt
  const old = dayLayers.get(d.day);
  if (old) old.setLatLngs(latlngs).setStyle(style);                      // cập nhật, không vẽ chồng
  else dayLayers.set(d.day, L.polyline(latlngs, style).addTo(map));
}

function setAdvisory({ id, text, source }) {
  const el = document.querySelector(`[data-advisory-id="${id}"]`);
  if (!el || !text) return;
  el.textContent = text;                           // textContent: an toàn XSS
  el.dataset.source = source || 'deterministic';   // 'ai' | 'deterministic' -> tuỳ CSS
}

function startPlanStream(plan, map) {
  (plan.advisories || []).forEach(setAdvisory);    // hiện ngay text xác định có sẵn trong response
  const stream = plan.stream;
  if (!stream || !stream.events_url) return () => {};

  const handlers = {
    day_route: (d) => drawDayRoute(map, d),
    advisory: (d) => { if (d.status === 'done') setAdvisory(d); },
    done: () => es.close(),
  };
  const es = new EventSource(stream.events_url);
  Object.entries(handlers).forEach(([ev, fn]) =>
    es.addEventListener(ev, (e) => { try { fn(JSON.parse(e.data)); } catch (err) { console.error(`[SSE:${ev}]`, err); } }));

  es.onerror = () => {
    if (es.readyState !== EventSource.CLOSED) return;   // CONNECTING: trình duyệt tự nối lại + Last-Event-ID
    fetch(stream.poll_url).then((r) => r.json())        // đã đóng hẳn (404/proxy đệm SSE) -> poll một lần
      .then((j) => j.events.forEach(({ event, data }) => handlers[event] && handlers[event](data)))
      .catch((err) => console.warn('[SSE] poll thất bại, giữ nguyên text xác định', err));
  };
  return () => es.close();
}
