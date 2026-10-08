import { useEffect, useState } from 'react';
import { filesApi, type Meta } from '../api/files';

let cache: Promise<Meta> | null = null;

export function loadMeta(): Promise<Meta> {
  cache ??= filesApi.meta().catch((error: unknown) => {
    cache = null;
    throw error;
  });
  return cache;
}

export function resetMetaCache(): void {
  cache = null;
}

export function useMeta(): Meta | null {
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => {
    let alive = true;
    loadMeta()
      .then((loaded) => { if (alive) setMeta(loaded); })
      .catch(() => undefined);
    return () => { alive = false; };
  }, []);
  return meta;
}
