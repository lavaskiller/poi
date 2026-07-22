import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import styles from "./MapPicker.module.css";

interface LatLon {
  lat: number;
  lon: number;
}

interface MapPickerProps {
  /** photo capture location — a fixed reference marker, always shown */
  photo?: LatLon;
  /** the query / reference point (draggable when onChange is given) */
  point: LatLon;
  /** location of the currently selected candidate — pinned + panned to */
  selected?: LatLon | null;
  onChange?: (lat: number, lon: number) => void;
}

export default function MapPicker({ photo, point, selected, onChange }: MapPickerProps) {
  const elRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const selectedRef = useRef<L.Marker | null>(null);
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

    mapRef.current = map;
    setTimeout(() => map.invalidateSize(), 60);
    return () => {
      map.remove();
      if (inner.parentNode === host) host.removeChild(inner);
      mapRef.current = null;
      selectedRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // reactively pin the selected candidate's location
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
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
      const icon = L.divIcon({ className: styles.selectedPin, iconSize: [20, 20], iconAnchor: [10, 10] });
      selectedRef.current = L.marker(ll, { icon, interactive: false })
        .addTo(map)
        .bindTooltip("selected", { direction: "top", offset: [0, -10] });
    }
    map.panTo(ll);
  }, [selected?.lat, selected?.lon]);

  return <div ref={elRef} className={styles.map} />;
}
