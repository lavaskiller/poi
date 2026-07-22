import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import styles from "./MapPicker.module.css";

interface LatLon {
  lat: number;
  lon: number;
}

export type MapCandidateKind = "default" | "gt" | "pick" | "hit";

export interface MapCandidate {
  lat: number;
  lon: number;
  rank?: number;
  name?: string;
  kind?: MapCandidateKind;
}

interface MapPickerProps {
  /** photo capture location — a fixed reference marker, always shown */
  photo?: LatLon;
  /** the query / reference point (draggable when onChange is given) */
  point: LatLon;
  /** location of the currently selected candidate — pinned + panned to */
  selected?: LatLon | null;
  /** MapKit (or other) nearby candidates to plot */
  candidates?: MapCandidate[];
  /**
   * Outer search radius in meters around photo (fallback: point).
   * Fixed probe/app radii should be passed here (e.g. MapKit wide 250 m) —
   * do not infer from max candidate distance.
   */
  radiusM?: number | null;
  /**
   * Optional inner radius (e.g. MapKit strict 80 m). Drawn dashed.
   */
  radiusInnerM?: number | null;
  onChange?: (lat: number, lon: number) => void;
}

const KIND_CLASS: Record<MapCandidateKind, string> = {
  default: styles.candPin,
  gt: styles.candPinGt,
  pick: styles.candPinPick,
  hit: styles.candPinHit,
};

function isFiniteLatLon(p: LatLon | null | undefined): p is LatLon {
  return !!p && Number.isFinite(p.lat) && Number.isFinite(p.lon);
}

export default function MapPicker({
  photo,
  point,
  selected,
  candidates,
  radiusM,
  radiusInnerM,
  onChange,
}: MapPickerProps) {
  const elRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const selectedRef = useRef<L.Marker | null>(null);
  const overlayRef = useRef<L.LayerGroup | null>(null);
  const cbRef = useRef(onChange);
  cbRef.current = onChange;

  useEffect(() => {
    const host = elRef.current;
    if (!host || mapRef.current) return;
    const draggable = !!onChange;
    // Fresh inner node each mount so React StrictMode's double-invoke can't hit
    // Leaflet's "Map container is already initialized".
    const inner = document.createElement("div");
    inner.style.width = "100%";
    inner.style.height = "100%";
    host.appendChild(inner);
    const map = L.map(inner, { attributionControl: false }).setView([point.lat, point.lon], 17);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19 }).addTo(map);

    // fixed photo-location marker
    if (photo) {
      const photoIcon = L.divIcon({ className: styles.photoPin, iconSize: [16, 16], iconAnchor: [8, 8] });
      L.marker([photo.lat, photo.lon], { icon: photoIcon, interactive: false })
        .addTo(map)
        .bindTooltip("photo location", { direction: "top", offset: [0, -8] });
    }

    // query point (draggable)
    const pointIcon = L.divIcon({ className: styles.pin, iconSize: [18, 18], iconAnchor: [9, 9] });
    const marker = L.marker([point.lat, point.lon], { draggable, icon: pointIcon }).addTo(map);
    if (draggable) {
      marker.on("dragend", () => {
        const p = marker.getLatLng();
        cbRef.current?.(p.lat, p.lng);
      });
      map.on("click", (e: L.LeafletMouseEvent) => {
        marker.setLatLng(e.latlng);
        cbRef.current?.(e.latlng.lat, e.latlng.lng);
      });
    }

    overlayRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    // invalidateSize after layout; cancel on teardown so we never touch a
    // removed map (StrictMode remount + headless teardown race → _leaflet_pos).
    let cancelled = false;
    const sizeTimer = window.setTimeout(() => {
      if (!cancelled && mapRef.current === map) {
        try {
          map.invalidateSize();
        } catch {
          /* map already torn down */
        }
      }
    }, 60);
    return () => {
      cancelled = true;
      window.clearTimeout(sizeTimer);
      map.remove();
      if (inner.parentNode === host) host.removeChild(inner);
      mapRef.current = null;
      selectedRef.current = null;
      overlayRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // reactively pin the selected candidate's location
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getContainer()) return;
    try {
      if (!selected || !Number.isFinite(selected.lat) || !Number.isFinite(selected.lon)) {
        if (selectedRef.current) {
          map.removeLayer(selectedRef.current);
          selectedRef.current = null;
        }
        return;
      }
      const ll: L.LatLngExpression = [selected.lat, selected.lon];
      if (selectedRef.current) {
        selectedRef.current.setLatLng(ll);
      } else {
        const icon = L.divIcon({
          className: styles.selectedPin,
          iconSize: [20, 20],
          iconAnchor: [10, 10],
        });
        selectedRef.current = L.marker(ll, { icon, interactive: false })
          .addTo(map)
          .bindTooltip("selected", { direction: "top", offset: [0, -10] });
      }
      map.panTo(ll);
    } catch {
      /* map mid-teardown */
    }
  }, [selected?.lat, selected?.lon]);

  // candidates + search-radius circles
  useEffect(() => {
    const map = mapRef.current;
    const group = overlayRef.current;
    if (!map || !group || !map.getContainer()) return;
    group.clearLayers();

    const center = isFiniteLatLon(photo) ? photo : isFiniteLatLon(point) ? point : null;
    const list = (candidates || []).filter(
      (c) => Number.isFinite(c.lat) && Number.isFinite(c.lon),
    );

    const outer = radiusM != null && Number.isFinite(radiusM) && radiusM > 0 ? radiusM : null;
    const inner =
      radiusInnerM != null && Number.isFinite(radiusInnerM) && radiusInnerM > 0
        ? radiusInnerM
        : null;

    if (center && outer != null) {
      L.circle([center.lat, center.lon], {
        radius: outer,
        className: styles.radiusOuter,
        color: "var(--accent-default)",
        fillColor: "var(--accent-default)",
        fillOpacity: 0.08,
        weight: 1.5,
        opacity: 0.55,
        interactive: false,
      })
        .bindTooltip(`${Math.round(outer)} m search radius`, {
          sticky: true,
          direction: "center",
        })
        .addTo(group);
    }
    if (center && inner != null && (outer == null || inner < outer * 0.98)) {
      L.circle([center.lat, center.lon], {
        radius: inner,
        className: styles.radiusInner,
        color: "var(--accent-default)",
        fill: false,
        weight: 1.5,
        opacity: 0.75,
        dashArray: "5 4",
        interactive: false,
      })
        .bindTooltip(`${Math.round(inner)} m strict radius`, {
          sticky: true,
          direction: "center",
        })
        .addTo(group);
    }

    for (const c of list) {
      const kind: MapCandidateKind = c.kind || "default";
      const label = c.rank != null ? String(c.rank) : "·";
      const icon = L.divIcon({
        className: `${styles.candPinBase} ${KIND_CLASS[kind]}`,
        html: `<span class="${styles.candRank}">${label}</span>`,
        iconSize: [22, 22],
        iconAnchor: [11, 11],
      });
      const tip = [c.rank != null ? `#${c.rank}` : null, c.name].filter(Boolean).join(" · ");
      L.marker([c.lat, c.lon], { icon, interactive: true, zIndexOffset: kind === "default" ? 0 : 200 })
        .addTo(group)
        .bindTooltip(tip || "candidate", { direction: "top", offset: [0, -10] });
    }

    // Prefer the fixed outer radius so short lists don't zoom in past the
    // actual search window (few POIs ≠ smaller radius).
    //
    // IMPORTANT: never call getBounds() on a Circle that is not on a map —
    // Leaflet Circle.getBounds needs map projection (layerPointToLatLng) and
    // throws if _map is undefined, which unmounts the whole page (no boundary).
    // LatLng.toBounds(sizeInMeters) is map-free and uses diameter = 2 * radius.
    try {
      if (center && outer != null) {
        const bounds = L.latLng(center.lat, center.lon).toBounds(outer * 2);
        map.fitBounds(bounds.pad(0.08), { maxZoom: 18, animate: false });
      } else if (list.length >= 1 && center) {
        const boundsPts: L.LatLngExpression[] = [[center.lat, center.lon]];
        for (const c of list) boundsPts.push([c.lat, c.lon]);
        map.fitBounds(L.latLngBounds(boundsPts).pad(0.35), { maxZoom: 18, animate: false });
      }
    } catch {
      // Map may be mid-teardown (StrictMode remount); skip fit this pass.
    }
  }, [candidates, radiusM, radiusInnerM, photo?.lat, photo?.lon, point.lat, point.lon]);

  return <div ref={elRef} className={styles.map} />;
}
