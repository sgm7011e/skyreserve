// Keycloak configuration matching Tutorial 12 conventions.
// Auto-detects local Docker Compose (port 8180) vs Group 8 K3s domain.
const defaultKeycloakUrl =
  window.location.hostname === 'group-8-m7011e-ltu.se'
    ? 'https://keycloak.group-8-m7011e-ltu.se'
    : `http://${window.location.hostname}:8180`;

export const keycloakConfig = {
  url: import.meta.env.VITE_KEYCLOAK_URL || defaultKeycloakUrl,
  realm: import.meta.env.VITE_KEYCLOAK_REALM || 'skyreserve',
  clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID || 'skyreserve-frontend',
};
