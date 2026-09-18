import { request } from '../../../packages/web/client.js';

function requireObject(response, name) {
  if (!response.body || typeof response.body !== 'object' || Array.isArray(response.body)) {
    throw new Error(`The target returned an invalid ${name} response.`);
  }
  return response;
}

function requireIdentifier(response, field, name) {
  requireObject(response, name);
  if (typeof response.body[field] !== 'string' || !response.body[field]) {
    throw new Error(`The target returned an invalid ${name} response.`);
  }
  return response;
}

export const api = {
  health: async (options = {}) => {
    const response = requireObject(await request('/api/health', options), 'health');
    if (
      !['status', 'api', 'redis', 'worker'].every((key) => typeof response.body[key] === 'string')
    ) {
      throw new Error('The target returned an invalid health response.');
    }
    return response;
  },
  probe: async (options = {}) => requireObject(await request('/api/probe', options), 'handler'),
  login: async (username, options = {}) =>
    requireIdentifier(
      await request('/api/login', {
        ...options,
        method: 'POST',
        body: { username },
      }),
      'session_id',
      'session',
    ),
  enqueue: async (payload, options = {}) =>
    requireIdentifier(
      await request('/api/jobs', {
        ...options,
        method: 'POST',
        body: { payload },
      }),
      'job_id',
      'enqueue',
    ),
  jobs: async (options = {}) => {
    const response = requireObject(await request('/api/jobs?limit=50', options), 'jobs');
    if (
      !Array.isArray(response.body.jobs) ||
      response.body.jobs.some(
        (job) =>
          !job ||
          Array.isArray(job) ||
          typeof job.id !== 'string' ||
          !job.id ||
          typeof job.status !== 'string',
      )
    ) {
      throw new Error('The target returned an invalid jobs response.');
    }
    return response;
  },
};
