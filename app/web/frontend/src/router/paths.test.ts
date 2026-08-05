import { isSafeReportFilename, routePaths } from './paths.ts';

const assertEqual = (actual: unknown, expected: unknown): void => {
  if (actual !== expected) {
    throw new Error(`Expected ${String(expected)}, received ${String(actual)}`);
  }
};

assertEqual(routePaths.task('T 1'), '/tasks/T%201');
assertEqual(routePaths.taskActivity('T 1'), '/tasks/T%201/activity');
assertEqual(
  routePaths.report('Alpha_Report_T1_2.md'),
  '/reports/Alpha_Report_T1_2.md'
);

assertEqual(isSafeReportFilename('Alpha_Report_T1_2.md'), true);
assertEqual(isSafeReportFilename('../secret.md'), false);
assertEqual(isSafeReportFilename('linked/secret.md'), false);
assertEqual(isSafeReportFilename('report<script>.md'), false);
assertEqual(isSafeReportFilename('javascript.md?redirect=1'), false);

console.log('route contract checks passed');
