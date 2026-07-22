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
  onChange?: (lat: number, lon: number) => void;
}

export default function MapPicker({ photo, point, onChange }: MapPickerProps) {
  const elRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
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
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <div ref={elRef} className={styles.map} />;
}
