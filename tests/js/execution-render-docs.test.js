/**
 * Node tests for execution-render-docs (pure escape helper).
 * Run: node --test tests/js/execution-render-docs.test.js
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const renderDocsPath = path.join(
  __dirname,
  '..',
  '..',
  'app',
  'core',
  'frontend',
  'js',
  'execution-render-docs.js'
);
const { escapeInlineMarkdownContent } = require(renderDocsPath);

test('escapeInlineMarkdownContent escapes HTML and preserves newlines as br', () => {
  assert.equal(
    escapeInlineMarkdownContent('<script>&\n'),
    '&lt;script&gt;&amp;<br>'
  );
});

test('escapeInlineMarkdownContent handles empty', () => {
  assert.equal(escapeInlineMarkdownContent(null), '');
  assert.equal(escapeInlineMarkdownContent(''), '');
});
