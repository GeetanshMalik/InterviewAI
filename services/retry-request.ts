type RetryableRequestOptions<T> = {
  attempts?: number;
  baseDelayMs?: number;
  isRetryable?: (error: unknown) => boolean;
  onRetry?: (error: unknown, attempt: number) => void;
  request: () => Promise<T>;
};

const defaultRetryableMessageTokens = [
  "cannot reach backend",
  "timed out",
  "failed to fetch",
  "networkerror",
  "load failed",
  "backend request",
];

export const isTransientBackendError = (error: unknown) => {
  if (!(error instanceof Error)) return false;
  const message = error.message.toLowerCase();
  return defaultRetryableMessageTokens.some((token) => message.includes(token));
};

const sleep = (delayMs: number) => new Promise((resolve) => setTimeout(resolve, delayMs));

export async function retryRequest<T>({
  attempts = 3,
  baseDelayMs = 800,
  isRetryable = isTransientBackendError,
  onRetry,
  request,
}: RetryableRequestOptions<T>): Promise<T> {
  let lastError: unknown = null;
  const totalAttempts = Math.max(1, attempts);

  for (let attempt = 1; attempt <= totalAttempts; attempt += 1) {
    try {
      return await request();
    } catch (error) {
      lastError = error;
      if (attempt >= totalAttempts || !isRetryable(error)) {
        throw error;
      }
      onRetry?.(error, attempt);
      await sleep(baseDelayMs * attempt);
    }
  }

  throw lastError;
}
