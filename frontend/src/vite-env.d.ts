/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_ADMIN_PASS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
