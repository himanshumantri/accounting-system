import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// base './' keeps asset paths relative, so the site works at the root of a domain and under a
// GitLab Pages project path (https://namespace.gitlab.io/project/) alike.
export default defineConfig({ base: './', plugins: [react()] });
