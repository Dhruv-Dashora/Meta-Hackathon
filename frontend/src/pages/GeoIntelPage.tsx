import { useEffect } from 'react';
import { MapContainer, TileLayer, useMap } from 'react-leaflet';
import { useSession } from '../state/session';
import { Badge } from '../ui/Badge';
import { Banner } from '../ui/Banner';
import { Card, PageTitle, SectionTitle } from '../ui/Card';
import { plural } from '../ui/format';

// Hidden Leaflet containers need a resize nudge when the view is shown
// again (views stay mounted so results are never lost).
function ResizeOnShow() {
  const map = useMap();
  useEffect(() => {
    const onHash = () => {
      window.setTimeout(() => map.invalidateSize(), 50);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, [map]);
  return null;
}

// Corridor map plus operator location context. No spatial analysis is
// performed or claimed; supplied locations stay unverified.
export default function GeoIntelPage() {
  const { incident } = useSession();
  const geo = incident.dossier?.geo_context ?? null;

  return (
    <section>
      <PageTitle
        title="Geospatial Intelligence"
        subtitle="Gyirong–Rasuwa corridor map with operator location context."
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Card className="min-w-0">
          <MapContainer
            center={[28.2, 85.6]}
            zoom={9}
            style={{ height: 480, width: '100%' }}
          >
            <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
            <ResizeOnShow />
          </MapContainer>
        </Card>
        <div className="grid min-w-0 content-start gap-4">
          <Card>
            <SectionTitle>Operator location</SectionTitle>
            {geo && geo.status === 'provided' ? (
              <div className="grid gap-2">
                <p>
                  <Badge>Operator-provided — unverified</Badge>
                </p>
                {geo.location_label && (
                  <p className="text-lg font-medium">{geo.location_label}</p>
                )}
                {geo.latitude != null && (
                  <p>
                    {geo.latitude}, {geo.longitude}
                  </p>
                )}
                {geo.geojson_feature_count != null && (
                  <p>{plural(geo.geojson_feature_count ?? 0, 'GeoJSON feature')} supplied.</p>
                )}
                <p className="text-slate-600">{geo.note}</p>
              </div>
            ) : (
              <p className="text-slate-600">
                No operator location in this session. Build an incident report
                with a location label, coordinates, or GeoJSON to see it here —
                always marked unverified.
              </p>
            )}
          </Card>
          <Banner>
            The map shows the corridor only. Image contents are never placed on
            this map, and no distances, routes, or exposure areas are computed.
          </Banner>
        </div>
      </div>
    </section>
  );
}
