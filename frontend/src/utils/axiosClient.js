import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_URL || '';

const axiosInstance = axios.create({
  baseURL: API_BASE,
  timeout: 120000,
  withCredentials: true, // allow cookies (important for CSRF + SPCS flows)
});

/**
 * Ensure we have a CSRF token cookie and set it as a default header for axios
 * Uses the double-submit cookie pattern: backend sets cookie and returns token
 */
export async function initCsrf() {
  try {
    const res = await axiosInstance.get('/api/csrf-token', { timeout: 5000 });
    const token = res?.data?.csrf;
    if (token) {
      axiosInstance.defaults.headers['X-XSRF-TOKEN'] = token;
    }
  } catch (e) {
    // Non-blocking - CSRF endpoint might not be configured in non-Snowflake environments
    // eslint-disable-next-line no-console
    console.warn('Unable to initialize CSRF token', e?.message || e);
  }
}

export default axiosInstance;
export { axiosInstance };
