/** @type {import('jest').Config} */
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  roots: ['<rootDir>/app/api'],
  testMatch: ['**/__tests__/**/*.test.ts'],
  setupFiles: ['<rootDir>/app/api/test/setupEnv.ts'],
  clearMocks: true,
  moduleFileExtensions: ['ts', 'js', 'json'],
};
