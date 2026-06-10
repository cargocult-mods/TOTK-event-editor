// ============================================================
//  main.js — Cytoscape-based rewrite
//  Replaces: d3 v3, dagre-d3, graphlib (separate instance)
//  Requires: cytoscape.min.js, dagre.min.js, cytoscape-dagre.js,
//            context-menu.js (vanilla replacement)
// ============================================================

// ── Global state (unchanged names/semantics) ─────────────────
const SHOW_PROFILER = true; // Set to false to disable the performance profiler HUD
let graph;
let widget;
let cpuTimeHistory = [];
let fpsContainer = null;
let lastFrameTime = performance.now();
let frameCount = 0;
let lastFpsUpdate = performance.now();
let currentFps = 60;
let lastLayoutTime = 0;
let lastUpdateTime = 0;
let lastUpdatePath = 'None';
let minFps = 1000;
let maxFps = 0;
let eventNamesVisible = false;
let eventParamVisible = false;
let eventMessagesVisible = false;
let actionsProhibited = false;
let isDeleting = false;
let suppressNextViewportAdjustment = false;
let hasHiddenEntryPoints = false;
let resetViewportOnNextLoad = false;
let preservedViewport = null;
let preservedFocusNodeId = null;
let preservedFocusPoint = null;
const GRAPH_TRANSITION_MS = 500;
let pendingLoadFinalizeToken = 0;
let nextGraphTransitionMs = GRAPH_TRANSITION_MS;
let graphSearchQuery = '';
let graphSearchCaseInsensitive = true;
let graphSearchScope = 'all';
let graphSearchMatches = [];
let graphSearchIndex = -1;
let renderMessageTagsAsStyling = true;
let showNonTextMessageTags = true;
let includeMessageBlankLines = true;
let showMessageBubbleBreaks = true;
const LABEL_WRAP_LENGTH = 44;
const MESSAGE_WRAP_LENGTH = 62;
const MESSAGE_BUBBLE_SOURCE_LINE_LIMIT = 3;
const MESSAGE_SEPARATOR = '-'.repeat(30);
const MESSAGE_BLANK_LINE = '\u00A0';
const MESSAGE_BUBBLE_BREAK_LINE = '\u2063';
const MESSAGE_TAG_REGEX = /(\{\{[^{}\n]+\}\})/g;
const MESSAGE_TAG_TOKEN_REGEX = /^\{\{[^{}\n]+\}\}$/;
const WRAP_TOKEN_REGEX = /\{\{[^{}\n]+\}\}|[ \t]+|[^\s{}]+/g;
const MESSAGE_TAG_STYLE_KEYS = ['fill', 'font-weight', 'font-style', 'font-size', 'font-family'];
const MESSAGE_TAG_DEFAULT_COLOR = '#fffeed';
const TOTK_MESSAGE_TAG_COLORS = {
  '-1': MESSAGE_TAG_DEFAULT_COLOR,
  '0': '#ff6634',
  '1': '#58d7ee',
  '2': '#b8bcc4',
  '3': '#f06a6a',
  '4': '#72d180',
  '5': '#d49bff',
};
const MESSAGE_TAG_COLOR_PALETTE = [
  '#fffeed', '#f06a6a', '#72d180', '#67b7ff', '#f2c55c', '#d49bff',
  '#74d7d0', '#ff9e64', '#cfd7df', '#9ec5ff', '#ffd1dc', '#d5f06a',
];

const WHITELISTED_PARAMS = new Set(['MessageId', 'ASName']);

// ── Utility helpers (unchanged) ───────────────────────────────

function isMultiSelectEvent(event) {
  return !!(event && (event.ctrlKey || event.metaKey));
}

function formatNodeParamValue(value, key = null) {
  if (typeof key === 'string' && /^ChoiceLabel\d+$/i.test(key)) {
    if (typeof value === 'number' && Number.isFinite(value) && value >= 0) {
      return Math.trunc(value).toString().padStart(4, '0');
    }
    if (typeof value === 'string' && /^\s*\d+\s*$/.test(value)) {
      return value.trim().padStart(4, '0');
    }
  }
  return typeof value === 'number' ? value.toFixed(6).replace(/\.?0*$/, '') : `${value}`;
}

function normalizeMessageLine(line) {
  return `${line}`
    .replace(/([.!?…])([A-Z])/g, '$1 $2')
    .replace(/[ \t]+/g, ' ')
    .trim();
}

function pushMessageBubbleBreak(lines) {
  if (!lines.length || lines[lines.length - 1] === MESSAGE_BUBBLE_BREAK_LINE) {
    return;
  }
  lines.push(MESSAGE_BUBBLE_BREAK_LINE);
}

function normalizeMessageText(text) {
  const normalized = `${text}`.replace(/\r\n/g, '\n').trim();
  if (!normalized) {
    return '';
  }

  const lines = [];
  let sourceTextLineCount = 0;
  let inBlankLineGroup = false;
  for (const rawLine of normalized.split('\n')) {
    const line = normalizeMessageLine(rawLine);
    if (!line) {
      if (includeMessageBlankLines) {
        lines.push(MESSAGE_BLANK_LINE);
      }
      if (showMessageBubbleBreaks && !inBlankLineGroup && sourceTextLineCount > 0) {
        pushMessageBubbleBreak(lines);
      }
      sourceTextLineCount = 0;
      inBlankLineGroup = true;
      continue;
    }

    inBlankLineGroup = false;
    lines.push(line);
    if (messageLineVisibleText(line)) {
      sourceTextLineCount += 1;
    }

    const forcedBreak = lineHasPageBreakTag(line);
    if (showMessageBubbleBreaks && (forcedBreak || sourceTextLineCount >= MESSAGE_BUBBLE_SOURCE_LINE_LIMIT)) {
      pushMessageBubbleBreak(lines);
      sourceTextLineCount = 0;
    }
  }

  while (lines.length && (lines[lines.length - 1] === MESSAGE_BLANK_LINE || lines[lines.length - 1] === MESSAGE_BUBBLE_BREAK_LINE)) {
    lines.pop();
  }
  return lines.join('\n');
}

function isMessageTagToken(token) {
  return MESSAGE_TAG_TOKEN_REGEX.test(token);
}

function isWhitespaceToken(token) {
  return /^[ \t]+$/.test(token);
}

function isHiddenMessageFormatToken(token) {
  return renderMessageTagsAsStyling && isMessageTagToken(token) && isMessageFormatTag(parseMessageTag(token));
}

function isMessageTagHidden(tag) {
  return (renderMessageTagsAsStyling && isMessageFormatTag(tag)) ||
    (!showNonTextMessageTags && !isMessageFormatTag(tag));
}

function isHiddenMessageTagToken(token) {
  return isMessageTagToken(token) && isMessageTagHidden(parseMessageTag(token));
}

function isMessagePageBreakTagToken(token) {
  return isMessageTagToken(token) && parseMessageTag(token).name === 'pageBreak';
}

function messageTokenVisibleText(token) {
  if (!isMessageTagToken(token)) {
    return token;
  }
  const tag = parseMessageTag(token);
  if (isMessageTagHidden(tag)) {
    return '';
  }
  return renderMessageTagsAsStyling ? formatMessageTagPreview(tag) : token;
}

function wrapLabelText(text, maxLength = LABEL_WRAP_LENGTH) {
  const normalized = `${text}`.replace(/\r\n/g, '\n');
  const wrappedLines = [];
  for (const sourceLine of normalized.split('\n')) {
    const line = sourceLine.trim();
    if (!line) {
      if (includeMessageBlankLines) {
        wrappedLines.push(MESSAGE_BLANK_LINE);
      }
      continue;
    }

    let current = '';
    let currentVisibleLength = 0;
    let currentHasHiddenFormatTag = false;
    let pendingSpace = '';
    const flushCurrent = () => {
      const trimmed = current.replace(/[ \t]+$/, '');
      if (trimmed && (currentVisibleLength > 0 || currentHasHiddenFormatTag)) {
        wrappedLines.push(trimmed);
      }
      current = '';
      currentVisibleLength = 0;
      currentHasHiddenFormatTag = false;
      pendingSpace = '';
    };

    const tokens = line.match(WRAP_TOKEN_REGEX) || [];
    for (const token of tokens) {
      if (isWhitespaceToken(token)) {
        if (current) {
          pendingSpace = ' ';
        }
        continue;
      }

      const visibleText = messageTokenVisibleText(token);
      const visibleLength = visibleText.length;
      const hiddenTagToken = isHiddenMessageTagToken(token);

      if (hiddenTagToken) {
        if (isHiddenMessageFormatToken(token) || isMessagePageBreakTagToken(token)) {
          currentHasHiddenFormatTag = true;
        }
        current += token;
        continue;
      }

      const separator = pendingSpace && currentVisibleLength > 0 ? pendingSpace : '';
      const candidateVisibleLength = currentVisibleLength + separator.length + visibleLength;
      if (current && visibleLength > 0 && candidateVisibleLength > maxLength) {
        flushCurrent();
      }

      if (!isMessageTagToken(token) && visibleLength > maxLength && !current) {
        for (let i = 0; i < token.length; i += maxLength) {
          wrappedLines.push(token.slice(i, i + maxLength));
        }
        continue;
      }

      if (pendingSpace && currentVisibleLength > 0) {
        current += pendingSpace;
        currentVisibleLength += pendingSpace.length;
      }
      pendingSpace = '';
      current += token;
      currentVisibleLength += visibleLength;
    }

    flushCurrent();
  }
  return wrappedLines;
}

function messageLineVisibleText(line) {
  return `${line}`.split(MESSAGE_TAG_REGEX)
    .filter((part) => part.length > 0 && !MESSAGE_TAG_TOKEN_REGEX.test(part))
    .join('')
    .split(MESSAGE_BLANK_LINE).join('')
    .split(MESSAGE_BUBBLE_BREAK_LINE).join('')
    .trim();
}

function messageLineLayoutText(line) {
  if (line === MESSAGE_BLANK_LINE || line === MESSAGE_BUBBLE_BREAK_LINE) {
    return line;
  }

  const parts = `${line}`.split(MESSAGE_TAG_REGEX).filter((part) => part.length > 0);
  const layoutText = parts.map((part) => {
    if (!MESSAGE_TAG_TOKEN_REGEX.test(part)) {
      return part;
    }
    return messageTokenVisibleText(part);
  }).join('');
  if (!layoutText && parts.some((part) => MESSAGE_TAG_TOKEN_REGEX.test(part))) {
    return MESSAGE_BLANK_LINE;
  }
  return layoutText;
}

function getNodeLayoutLabel(label) {
  return `${label}`.split('\n').map((line) => messageLineLayoutText(line)).join('\n');
}

function computeNodeDimensions(label) {
  const visibleLabel = `${getNodeLayoutLabel(label)}`.replace(/\r\n/g, '\n');
  const lines = visibleLabel ? visibleLabel.split('\n') : [''];
  const maxLineLength = lines.reduce((max, line) => Math.max(max, line.length), 0);
  const lineCount = Math.max(1, lines.length);

  const width = Math.min(420, Math.max(60, 12 + maxLineLength * 6.8 + Math.max(0, lineCount - 1) * 8));
  const height = Math.min(180, Math.max(28, 18 + lineCount * 14));

  return {
    width: Math.round(width),
    height: Math.round(height),
  };
}

function getNodePosition(entry) {
  const directPosition = entry && entry.position && Number.isFinite(entry.position.x) && Number.isFinite(entry.position.y)
    ? { x: entry.position.x, y: entry.position.y }
    : null;
  if (directPosition) {
    return directPosition;
  }

  const dataPosition = entry && entry.data && entry.data.position && Number.isFinite(entry.data.position.x) && Number.isFinite(entry.data.position.y)
    ? { x: entry.data.position.x, y: entry.data.position.y }
    : null;
  if (dataPosition) {
    return dataPosition;
  }

  const fallbackX = entry && entry.data && Number.isFinite(entry.data.x) ? entry.data.x : null;
  const fallbackY = entry && entry.data && Number.isFinite(entry.data.y) ? entry.data.y : null;
  return fallbackX != null && fallbackY != null ? { x: fallbackX, y: fallbackY } : null;
}

function hasStoredNodePositions(elements) {
  return elements.some((el) => el.group === 'nodes' && el.position && Number.isFinite(el.position.x) && Number.isFinite(el.position.y));
}

function lineHasPageBreakTag(line) {
  return `${line}`.split(MESSAGE_TAG_REGEX)
    .some((part) => isMessagePageBreakTagToken(part));
}

function applyTextBubbleBreaks(lines) {
  if (!showMessageBubbleBreaks) {
    return lines;
  }

  const withBreaks = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    withBreaks.push(line);
    if (line === MESSAGE_BLANK_LINE || line === MESSAGE_BUBBLE_BREAK_LINE) {
      continue;
    }

    const hasForcedBreak = lineHasPageBreakTag(line);
    const nextLine = index + 1 < lines.length ? lines[index + 1] : '';
    const nextLineAlreadyBreaks = nextLine === MESSAGE_BLANK_LINE ||
      nextLine === MESSAGE_BUBBLE_BREAK_LINE ||
      lineHasPageBreakTag(nextLine);
    if (hasForcedBreak && !nextLineAlreadyBreaks) {
      withBreaks.push(MESSAGE_BUBBLE_BREAK_LINE);
    }
  }

  while (withBreaks.length && withBreaks[withBreaks.length - 1] === MESSAGE_BUBBLE_BREAK_LINE) {
    withBreaks.pop();
  }
  return withBreaks;
}

function appendWrappedLabelLine(label, prefix, text) {
  const wrapped = wrapLabelText(text);
  if (!wrapped.length) {
    return `${label}\n${prefix}`;
  }
  let nextLabel = `${label}\n${prefix}${wrapped[0]}`;
  for (const continuation of wrapped.slice(1)) {
    nextLabel += `\n${continuation}`;
  }
  return nextLabel;
}

function appendWrappedLabelLineWithIndent(label, prefix, text, continuationPrefix = '  ') {
  const wrapped = wrapLabelText(text);
  if (!wrapped.length) {
    return `${label}\n${prefix}`;
  }
  let nextLabel = `${label}\n${prefix}${wrapped[0]}`;
  for (const continuation of wrapped.slice(1)) {
    nextLabel += `\n${continuationPrefix}${continuation}`;
  }
  return nextLabel;
}

function appendMessageIdBlock(label, messageId) {
  const rawMessageId = formatNodeParamValue(messageId);
  const separatorIndex = rawMessageId.indexOf(':');
  const msbtPath = separatorIndex >= 0 ? rawMessageId.slice(0, separatorIndex) : '';
  const labelId = separatorIndex >= 0 ? rawMessageId.slice(separatorIndex + 1) : rawMessageId;
  let nextLabel = `${label}\nMessage:`;
  if (msbtPath) {
    nextLabel = appendWrappedLabelLineWithIndent(nextLabel, '  MSBT: ', msbtPath, '        ');
  }
  return appendWrappedLabelLineWithIndent(nextLabel, '  ID:   ', labelId, '        ');
}

function appendMessageBlock(label, text) {
  const wrapped = applyTextBubbleBreaks(wrapLabelText(text, MESSAGE_WRAP_LENGTH));
  if (!wrapped.length) {
    return label;
  }

  let nextLabel = `${label}\n\n${MESSAGE_SEPARATOR}\n`;
  for (const line of wrapped) {
    nextLabel += `\n${line}`;
  }
  nextLabel += `\n\n${MESSAGE_SEPARATOR}\n`;
  return nextLabel;
}

function appendChoiceBlock(label, choices) {
  if (!choices || !choices.length) {
    return label;
  }

  let nextLabel = label;
  for (const choice of choices) {
    const choiceIndex = choice && choice.index != null ? choice.index : '';
    const choiceText = choice && typeof choice.text === 'string' ? normalizeMessageText(choice.text) : '';
    if (!choiceText) {
      continue;
    }
    const wrappedChoice = applyTextBubbleBreaks(wrapLabelText(choiceText));
    if (!wrappedChoice.length) {
      continue;
    }
    nextLabel = `${nextLabel}\nChoice ${choiceIndex}: ${wrappedChoice[0]}`;
    for (const continuation of wrappedChoice.slice(1)) {
      nextLabel += `\n${continuation}`;
    }
    nextLabel += `\n${MESSAGE_SEPARATOR}`;
  }
  return nextLabel;
}

function parseMessageTag(rawTag) {
  const inner = `${rawTag}`.replace(/^\{\{/, '').replace(/\}\}$/, '').trim();
  const firstSpace = inner.search(/\s/);
  const name = firstSpace >= 0 ? inner.slice(0, firstSpace) : inner;
  const argText = firstSpace >= 0 ? inner.slice(firstSpace + 1) : '';
  const args = {};
  const argRegex = /([A-Za-z0-9_:-]+)="([^"]*)"/g;
  let match;
  while ((match = argRegex.exec(argText)) !== null) {
    args[match[1]] = match[2];
  }
  return { raw: rawTag, name, args };
}

function normalizeMessageTagColorId(id) {
  if (id == null) {
    return null;
  }
  const numericId = parseInt(id, 10);
  if (Number.isNaN(numericId)) {
    return null;
  }
  if (numericId === 65535) {
    return '-1';
  }
  return `${numericId}`;
}

function messageTagColor(id) {
  const colorId = normalizeMessageTagColorId(id);
  if (colorId == null) {
    return '#b8bcc4';
  }
  if (TOTK_MESSAGE_TAG_COLORS[colorId]) {
    return TOTK_MESSAGE_TAG_COLORS[colorId];
  }
  const numericId = parseInt(id, 10);
  return MESSAGE_TAG_COLOR_PALETTE[((numericId % MESSAGE_TAG_COLOR_PALETTE.length) + MESSAGE_TAG_COLOR_PALETTE.length) % MESSAGE_TAG_COLOR_PALETTE.length];
}

function messageTagFontStyle(face) {
  if (!face) {
    return {};
  }
  const normalized = `${face}`.toLowerCase();
  if (normalized === 'default' || normalized === '-1') {
    return {};
  }
  if (normalized.includes('bold') || normalized.includes('title')) {
    return { 'font-weight': '700' };
  }
  if (normalized.includes('thin')) {
    return { 'font-weight': '300' };
  }
  if (normalized.includes('ancient')) {
    return { 'font-family': 'Georgia, serif', 'font-weight': '600' };
  }
  return {};
}

function messageTagSizeStyle(value) {
  const numericValue = parseInt(value, 10);
  if (Number.isNaN(numericValue)) {
    return {};
  }
  const clamped = Math.max(9, Math.min(28, 14 * (numericValue / 100)));
  return { 'font-size': `${clamped}px` };
}

function formatMessageTagPreview(tag) {
  if (tag.name === 'icon') {
    return `[${tag.args.type || 'icon'}]`;
  }
  if (tag.name === 'color') {
    return `[color ${tag.args.id || '?'}]`;
  }
  if (tag.name === 'font') {
    return `[font ${tag.args.face || '?'}]`;
  }
  if (tag.name === 'size') {
    return `[size ${tag.args.value || '?'}]`;
  }
  if (tag.name === 'delay') {
    return `[delay ${tag.args.frames || '?'}f]`;
  }
  if (/^delay(\d+)$/.test(tag.name)) {
    return `[delay ${tag.name.replace('delay', '')}f]`;
  }
  if (tag.name === 'pageBreak') {
    return '[page]';
  }
  if (tag.name === 'resetFontStyle') {
    return '[/style]';
  }
  if (tag.name === 'setEmotion') {
    return `[emotion ${tag.args.emotion || '?'}]`;
  }
  if (tag.name === 'setVoice') {
    return tag.args.asset ? `[voice ${tag.args.asset}]` : '[voice]';
  }
  if (tag.name.startsWith('tag:')) {
    return `[${tag.name}]`;
  }
  return `[${tag.name}]`;
}

function isMessageFormatTag(tag) {
  return ['color', 'font', 'size', 'setItalicFont', 'resetFontStyle'].includes(tag.name);
}

function applySvgTextStyle(element, style) {
  for (const key of MESSAGE_TAG_STYLE_KEYS) {
    if (style[key]) {
      element.setAttribute(key, style[key]);
    }
  }
}

function hasSvgTextStyle(style) {
  return MESSAGE_TAG_STYLE_KEYS.some((key) => !!style[key]);
}

function mutateMessageTextStyleForTag(tag, currentStyle) {
  const markerStyle = { fill: '#b8bcc4', 'font-weight': '600' };
  if (tag.name === 'color') {
    const colorId = normalizeMessageTagColorId(tag.args.id);
    const color = messageTagColor(tag.args.id);
    markerStyle.fill = color;
    if (colorId === '-1') {
      delete currentStyle.fill;
      delete currentStyle._colorId;
    } else {
      currentStyle.fill = color;
      currentStyle._colorId = colorId;
    }
  } else if (tag.name === 'font') {
    const fontStyle = messageTagFontStyle(tag.args.face);
    Object.assign(markerStyle, fontStyle);
    const fontFace = tag.args.face || '';
    const fontFaceKey = `${fontFace}`.toLowerCase();
    if (fontFaceKey === 'default' || fontFaceKey === '-1') {
      delete currentStyle['font-weight'];
      delete currentStyle['font-family'];
      delete currentStyle._fontFace;
    } else {
      delete currentStyle['font-weight'];
      delete currentStyle['font-family'];
      Object.assign(currentStyle, fontStyle);
      currentStyle._fontFace = fontFace;
    }
  } else if (tag.name === 'size') {
    const sizeStyle = messageTagSizeStyle(tag.args.value);
    Object.assign(markerStyle, sizeStyle);
    if (!Object.keys(sizeStyle).length) {
      delete currentStyle['font-size'];
      delete currentStyle._sizeValue;
    } else {
      Object.assign(currentStyle, sizeStyle);
      currentStyle._sizeValue = tag.args.value;
    }
  } else if (tag.name === 'setItalicFont') {
    if (currentStyle['font-style'] === 'italic') {
      delete currentStyle['font-style'];
    } else {
      currentStyle['font-style'] = 'italic';
      markerStyle['font-style'] = 'italic';
    }
  } else if (tag.name === 'resetFontStyle') {
    for (const key of Object.keys(currentStyle)) {
      delete currentStyle[key];
    }
  }
  return markerStyle;
}

// ── Node label building (unchanged) ──────────────────────────

function getMessageText(node) {
  if (!node || !node.data || typeof node.data._message_text !== 'string') {
    return '';
  }
  return normalizeMessageText(node.data._message_text);
}

function getChoiceItems(node) {
  if (!node || !node.data || !Array.isArray(node.data._choice_texts)) {
    return [];
  }
  return node.data._choice_texts;
}

function getNodeLabel(node) {
  const prefix = eventNamesVisible ? `${node.data.name}\n` : '';
  let label = `${node.id}`;

  if (node.node_type === 'entry') {
    label = `${node.data.name}`;
  }
  else if (node.node_type === 'action') {
    label = `${prefix}${node.data.actor}\n${node.data.action}`;
  }
  else if (node.node_type === 'switch') {
    label = `${prefix}${node.data.actor}\n${node.data.query}`;
  }
  else if (node.node_type === 'fork') {
    label = `${prefix}Fork`;
  }
  else if (node.node_type === 'join') {
    label = `${prefix}Join`;
  }
  else if (node.node_type === 'sub_flow') {
    label = `${prefix}${node.data.res_flowchart_name}\n<${node.data.entry_point_name}>`;
  }

  if (eventParamVisible && node.data.params) {
    for (const [key, value] of Object.entries(node.data.params)) {
      if (key === 'IsWaitFinish') {
        continue;
      }
      if (key === 'MessageId') {
        label = appendMessageIdBlock(label, value);
        continue;
      }
      label = appendWrappedLabelLine(label, `${key}: `, formatNodeParamValue(value, key));
    }
  }

  if (eventMessagesVisible && node.data && node.data.params && node.data.params.MessageId) {
    if (!eventParamVisible) {
      label = appendMessageIdBlock(label, node.data.params.MessageId);
    }
    const messageText = getMessageText(node);
    if (messageText) {
      label = appendMessageBlock(label, messageText);
    }
    label = appendChoiceBlock(label, getChoiceItems(node));
  }
  return label;
}

// ── Context menu action builders (unchanged logic) ────────────

function handleNodeContextMenu(id) {
  const actions = [];
  const selectedNodeIds = graph.renderer.getSelectedIds();
  const selectedCount = selectedNodeIds.length;

  const idx = parseInt(id, 10);
  const nodeData = graph.getNodeData(id);
  const nodeClass = nodeData ? (nodeData.node_type || '') : '';
  const classes = nodeClass.split(' ');

  // Build prev/next from the stored edge list on the graph
  const prevNodes = graph.getPrevNodes(id);
  const nextNodes = graph.getNextNodes(id);

  const addAction = (name, fn) => actions.push({ title: name, action: () => { setTimeout(fn, 60); } });
  const clearSelectionForDelete = () => {
    graph.renderer.clearSelectionWithoutEmittingSignal();
    widget.emitEventSelectedSignal(-1);
  };

  if (!actionsProhibited) {
    if (selectedCount) {
      addAction(selectedCount > 1 ? `Copy selected nodes (${selectedCount})` : 'Copy selected node', () => widget.copyEvents(selectedNodeIds));
      if (selectedCount > 1) {
        addAction(`Delete selected nodes (${selectedCount})`, () => {
          clearSelectionForDelete();
          isDeleting = true;
          widget.removeEvents(selectedNodeIds);
        });
      } else if (selectedNodeIds[0] !== idx) {
        addAction('Delete selected node', () => {
          clearSelectionForDelete();
          isDeleting = true;
          widget.removeEvents(selectedNodeIds);
        });
      }
      actions.push({ divider: true });
    }

    addAction('Paste copied events', () => widget.pasteEventsInto(idx));
    actions.push({ divider: true });

    if (idx >= 0) { // Event actions
      addAction('Add fork...', () => widget.addForkAt(idx));
      actions.push({ divider: true });

      if (!classes.includes('fork') && !classes.includes('join')) {
        addAction('Edit event...', () => widget.editEvent(idx));
      }
      if (classes.includes('switch')) {
        addAction('Edit cases...', () => widget.editSwitchBranches(idx));
      }
      if (classes.includes('fork')) {
        addAction('Edit branches...', () => widget.editForkBranches(idx));
      }
      if (!classes.includes('join')) {
        actions.push({ divider: true });
      }

      addAction('Add entry point here...', () => widget.addEntryPoint(idx));
      actions.push({ divider: true });

      if (!classes.includes('join')) {
        addAction('Add new parent...', () => widget.addEventAbove(prevNodes, idx));
      }

      if (classes.includes('action') || classes.includes('sub_flow') || classes.includes('join')) {
        addAction('Add new child...', () => widget.addEventBelow(idx));
        if (nextNodes.length) {
          addAction('Unlink child', () => widget.unlink(idx));
        } else {
          addAction('Link to event...', () => widget.link(idx));
        }
      }

      const oneBranchSwitchOrFork =
        nextNodes.length <= 1 && (classes.includes('fork') || classes.includes('switch'));
      const isOnlyEventInEntry =
        nextNodes.length === 0 && prevNodes.length === 1 && parseInt(prevNodes[0], 10) <= -1000;

      if (!isOnlyEventInEntry && (classes.includes('action') || classes.includes('sub_flow') || oneBranchSwitchOrFork)) {
        actions.push({ divider: true });
        addAction('Delete event', () => {
          clearSelectionForDelete();
          isDeleting = true;
          widget.removeEvent(prevNodes, idx);
        });
      }

    } else { // Entry point actions
      addAction('Add new child...', () => widget.addEntryPointChild(idx));
      actions.push({ divider: true });
      addAction('Delete entry point', () => widget.removeEntryPoint(idx));
    }

    actions.push({ divider: true });
  }

  if (classes.includes('sub_flow')) {
    addAction('Go to entry point', () => widget.goToSubflowEntryPoint(idx));
    actions.push({ divider: true });
  }

  addAction('Select connected events', () => graph.selectConnected(id));
  if (hasHiddenEntryPoints) {
    addAction('Show all events', () => widget.showAllEventsFromNode(idx));
  } else {
    addAction('Show only connected events', () => widget.showOnlyConnectedEvents(idx));
  }

  return actions;
}

function handleBackgroundContextMenu() {
  const actions = [];
  const selectedNodeIds = graph.renderer.getSelectedIds();
  const selectedCount = selectedNodeIds.length;
  const addAction = (name, fn) => actions.push({ title: name, action: () => { setTimeout(fn, 60); } });
  const clearSelectionForDelete = () => {
    graph.renderer.clearSelectionWithoutEmittingSignal();
    widget.emitEventSelectedSignal(-1);
  };

  if (!actionsProhibited) {
    addAction('Add event...', () => widget.addStandaloneEvent());
    addAction('Add fork...', () => widget.addFork());
    actions.push({ divider: true });

    if (selectedCount) {
      addAction(selectedCount > 1 ? `Copy selected nodes (${selectedCount})` : 'Copy selected node', () => widget.copyEvents(selectedNodeIds));
      addAction(selectedCount > 1 ? `Delete selected nodes (${selectedCount})` : 'Delete selected node', () => {
        clearSelectionForDelete();
        isDeleting = true;
        widget.removeEvents(selectedNodeIds);
      });
      actions.push({ divider: true });
    }
    addAction('Paste copied events', () => widget.pasteEvents());
    actions.push({ divider: true });
  }

  if (hasHiddenEntryPoints) {
    addAction('Show all events', () => widget.showAllEvents());
  }

  return actions;
}

// ── Cytoscape stylesheet ─────────────────────────────────────
//
// Node types: entry, action, switch, fork, join, sub_flow
// Selection and search-match states are applied as extra classes.

function buildCytoscapeStylesheet(isDark) {
  const bg = isDark ? '#3c3f41' : '#f5f5f5';
  const defaultNodeBg = isDark ? '#4a525e' : '#ffffff';
  const defaultNodeBorder = isDark ? '#7a8694' : '#888888';
  const labelColor = isDark ? '#f0f0f0' : '#222222';
  const edgeColor = isDark ? '#8a9ab0' : '#555555';
  const virtualEdgeColor = isDark ? '#5a6472' : '#aaaaaa';
  const edgeLabelBg = isDark ? '#3c3f41' : '#f5f5f5';
  const edgeLabelColor = isDark ? '#c0c8d4' : '#333333';

  return [
    {
      selector: 'core',
      style: {
        'active-bg-color': bg,
        'active-bg-opacity': 0,
        'selection-box-color': isDark ? '#2a82da' : '#1a73e8',
        'selection-box-opacity': 0.15,
        'selection-box-border-color': isDark ? '#2a82da' : '#1a73e8',
        'selection-box-border-width': 1,
      },
    },
    {
      selector: 'node',
      style: {
        'shape': 'round-rectangle',
        'background-color': defaultNodeBg,
        'border-color': defaultNodeBorder,
        'border-width': 1.5,
        'label': 'data(label)',
        'text-valign': 'center',
        'text-halign': 'center',
        'text-wrap': 'wrap',
        'font-family': 'Consolas, Menlo, Monaco, "Courier New", monospace',
        'font-size': '11px',
        'color': labelColor,
        'padding': '8px',
        'width': (ele) => ele.data('nodeWidth') || 60,
        'height': (ele) => ele.data('nodeHeight') || 28,
        'min-width': '60px',
        'min-height': '28px',
        'text-max-width': '320px',
        'overlay-opacity': 0,
      },
    },
    // Entry point nodes (id < -1000) — rounded pill style
    {
      selector: 'node.entry',
      style: {
        'background-color': isDark ? '#2d4a2d' : '#e6f4ea',
        'border-color': isDark ? '#4caf50' : '#34a853',
        'border-width': 2,
        'shape': 'round-rectangle',
        'font-weight': 'bold',
      },
    },
    // Action nodes
    {
      selector: 'node.action',
      style: {
        'background-color': isDark ? '#2a3a50' : '#e8f0fe',
        'border-color': isDark ? '#5588cc' : '#4285f4',
      },
    },
    // Switch nodes (query/condition)
    {
      selector: 'node.switch',
      style: {
        'background-color': isDark ? '#3a3020' : '#fef7e0',
        'border-color': isDark ? '#c8962a' : '#f9ab00',
        'shape': 'diamond',
      },
    },
    // Fork nodes
    {
      selector: 'node.fork',
      style: {
        'background-color': isDark ? '#3a2040' : '#fce8fd',
        'border-color': isDark ? '#a050b8' : '#9334e6',
        'shape': 'hexagon',
      },
    },
    // Join nodes
    {
      selector: 'node.join',
      style: {
        'background-color': isDark ? '#3a2040' : '#fce8fd',
        'border-color': isDark ? '#a050b8' : '#9334e6',
        'shape': 'hexagon',
      },
    },
    // Sub-flow nodes
    {
      selector: 'node.sub_flow',
      style: {
        'background-color': isDark ? '#3a2828' : '#fdecea',
        'border-color': isDark ? '#c04040' : '#d93025',
        'shape': 'round-rectangle',
        'border-style': 'double',
      },
    },
    // Selected state
    {
      selector: 'node.selected',
      style: {
        'border-color': isDark ? '#5aaaff' : '#1a73e8',
        'border-width': 3,
        'background-color': isDark ? '#1e3a5f' : '#d2e3fc',
      },
    },
    // Search match
    {
      selector: 'node.search-match',
      style: {
        'border-color': '#f9ab00',
        'border-width': 3,
        'background-color': isDark ? '#3a3010' : '#fff8e1',
      },
    },
    // Current search result (overrides search-match)
    {
      selector: 'node.search-current',
      style: {
        'border-color': '#ea4335',
        'border-width': 3.5,
        'background-color': isDark ? '#3a1010' : '#fde8e8',
      },
    },
    // Edges
    {
      selector: 'edge',
      style: {
        'width': 1.5,
        'line-color': edgeColor,
        'target-arrow-color': edgeColor,
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        'label': 'data(label)',
        'font-size': '10px',
        'color': edgeLabelColor,
        'text-background-color': edgeLabelBg,
        'text-background-opacity': 1,
        'text-background-padding': '2px',
        'text-border-width': 0,
        'overlay-opacity': 0,
        'arrow-scale': 1,
      },
    },
    {
      selector: 'edge.virtual',
      style: {
        'line-color': virtualEdgeColor,
        'target-arrow-color': virtualEdgeColor,
        'line-style': 'dashed',
        'width': 1,
        'label': '',
      },
    },
    // Highlighted edges for selected node
    {
      selector: 'edge.selected-in-edge',
      style: {
        'line-color': isDark ? '#4db6ff' : '#1a73e8',
        'target-arrow-color': isDark ? '#4db6ff' : '#1a73e8',
        'width': 2.5,
      },
    },
    {
      selector: 'edge.selected-out-edge',
      style: {
        'line-color': isDark ? '#ff9e64' : '#e65c00',
        'target-arrow-color': isDark ? '#ff9e64' : '#e65c00',
        'width': 2.5,
      },
    },
  ];
}

// ── Renderer (Cytoscape wrapper) ─────────────────────────────

class Renderer {
  constructor() {
    this.cy = null;
    this.selectedNodeIds = new Set();
    this.primarySelectedId = null;
    this.nodeWhitelist = null;
    this._panZoomStartTime = null;
  }

  // ── Init / stylesheet ───────────────────────────────────────

  _initCy() {
    const isDark = document.body.classList.contains('dark-mode');
    this.cy = cytoscape({
      container: document.getElementById('graph'),
      elements: [],
      style: buildCytoscapeStylesheet(isDark),
      layout: { name: 'preset' },
      minZoom: 0.05,
      maxZoom: 4,
      wheelSensitivity: 1,
      // Use the native canvas renderer for performance
      renderer: { name: 'canvas' },
    });

    // Register dagre layout
    // cytoscape-dagre is already loaded as a side-effect script

    this._bindEvents();
  }

  refreshStylesheet() {
    if (!this.cy) return;
    const isDark = document.body.classList.contains('dark-mode');
    this.cy.style(buildCytoscapeStylesheet(isDark));
  }

  // ── Event binding ───────────────────────────────────────────

  _bindEvents() {
    const cy = this.cy;

    // Pan/zoom start (for distinguishing click vs drag)
    cy.on('viewport', () => {
      this._panZoomStartTime = performance.now();
    });

    // Background click — clear selection
    cy.on('tap', (event) => {
      if (event.target === cy) {
        // Only clear if not a pan (panning also fires tap on background)
        if (this._panZoomStartTime == null || (performance.now() - this._panZoomStartTime) < 150) {
          this.clearSelection();
        }
      }
    });

    // Background right-click
    cy.on('cxttap', (event) => {
      if (event.target === cy) {
        const actions = handleBackgroundContextMenu();
        showContextMenu(actions, event.originalEvent.clientX, event.originalEvent.clientY);
      }
    });

    // Node click (select / multi-select)
    cy.on('tap', 'node', (event) => {
      const id = event.target.id();
      if (isMultiSelectEvent(event.originalEvent)) {
        this.toggleSelection(id);
      } else {
        this.select(id);
      }
      event.stopPropagation();
    });

    // Node double-click
    cy.on('dbltap', 'node', (event) => {
      if (actionsProhibited) {
        event.stopPropagation();
        return;
      }
      const id = event.target.id();
      const nodeData = graph.getNodeData(id);
      const nodeType = nodeData ? nodeData.node_type : '';
      const numericId = parseInt(id, 10);
      if (nodeType === 'entry') {
        widget.renameEntryPoint(numericId);
      } else if (nodeType === 'fork') {
        widget.editForkBranches(numericId);
      } else {
        widget.editEvent(numericId);
      }
      event.stopPropagation();
    });

    // Node right-click
    cy.on('cxttap', 'node', (event) => {
      const id = event.target.id();
      this.selectForContextMenu(id);
      const actions = handleNodeContextMenu(id);
      showContextMenu(actions, event.originalEvent.clientX, event.originalEvent.clientY);
      event.stopPropagation();
    });

    // Viewport change → CPU profiling
    cy.on('pan zoom', () => {
      if (SHOW_PROFILER) {
        const tStart = performance.now();
        const tEnd = performance.now();
        cpuTimeHistory.push(tEnd - tStart);
      }
    });
  }

  // ── Render ──────────────────────────────────────────────────

  render(elements, transitionMs = GRAPH_TRANSITION_MS) {
    if (!this.cy) {
      this._initCy();
    }

    // Filter by whitelist if set
    const filteredElements = this.nodeWhitelist
      ? elements.filter((el) => {
          if (el.group === 'nodes') return this.nodeWhitelist.has(el.data.id);
          if (el.group === 'edges') return this.nodeWhitelist.has(el.data.source) && this.nodeWhitelist.has(el.data.target);
          return false;
        })
      : elements;

    const cy = this.cy;
    const useStoredPositions = hasStoredNodePositions(filteredElements);

    cy.batch(() => {
      cy.elements().remove();
      cy.add(filteredElements);
    });

    const layout = cy.layout({
      name: useStoredPositions ? 'preset' : 'dagre',
      rankDir: 'TB',
      nodeSep: 40,
      edgeSep: 10,
      rankSep: 60,
      padding: 20,
      animate: useStoredPositions ? false : transitionMs > 0,
      animationDuration: transitionMs,
      fit: false,
    });

    layout.run();

    // Re-apply selection state
    this._refreshSelectionAfterRender();
  }

  fastUpdate(elements) {
    // Fast path: only labels changed, no layout needed. Just update
    // Cytoscape data and re-style without running dagre.
    if (!this.cy) return;
    const tStart = performance.now();
    lastUpdatePath = 'Fast In-Place';

    this.cy.batch(() => {
      for (const el of elements) {
        if (el.group !== 'nodes') continue;
        const cyNode = this.cy.getElementById(el.data.id);
        if (cyNode && cyNode.length) {
          cyNode.data('label', el.data.label);
          cyNode.data('rawLabel', el.data.rawLabel);
        }
      }
    });

    applySearchHighlights();
    this._refreshSelectionAfterRender();

    const tEnd = performance.now();
    lastUpdateTime = tEnd - tStart;
    lastLayoutTime = 0;
  }

  _refreshSelectionAfterRender() {
    if (!this.cy) return;
    this.cy.batch(() => {
      this.cy.nodes().removeClass('selected');
      for (const id of this.selectedNodeIds) {
        const el = this.cy.getElementById(`${id}`);
        if (el && el.length) el.addClass('selected');
      }
    });
    this._updateEdgeHighlights();
  }

  // ── Selection ───────────────────────────────────────────────

  select(id, emitSignal = true) {
    if (!this.cy) return;
    const numericId = parseInt(id, 10);
    this.clearSelectionWithoutEmittingSignal();
    const el = this.cy.getElementById(`${id}`);
    if (el && el.length) el.addClass('selected');
    this.selectedNodeIds.add(numericId);
    this.primarySelectedId = numericId;
    this._updateEdgeHighlights();
    if (emitSignal) {
      widget.emitEventSelectedSignal(numericId);
      widget.emitSelectedNodeIdsSignal(this.getSelectedIds());
    }
  }

  toggleSelection(id) {
    if (!this.cy) return;
    const numericId = parseInt(id, 10);
    const el = this.cy.getElementById(`${id}`);
    if (!el || !el.length) return;

    if (this.selectedNodeIds.has(numericId)) {
      el.removeClass('selected');
      this.selectedNodeIds.delete(numericId);
      if (this.primarySelectedId === numericId) {
        this.primarySelectedId = this.selectedNodeIds.size
          ? [...this.selectedNodeIds][0]
          : null;
      }
    } else {
      el.addClass('selected');
      this.selectedNodeIds.add(numericId);
      this.primarySelectedId = numericId;
    }

    this._updateEdgeHighlights();
    widget.emitEventSelectedSignal(this.getSelection());
    widget.emitSelectedNodeIdsSignal(this.getSelectedIds());
  }

  selectForContextMenu(id) {
    const numericId = parseInt(id, 10);
    const isSelected = this.selectedNodeIds.has(numericId);
    if (!isSelected) {
      this.select(id);
      return;
    }
    this.selectedNodeIds.add(numericId);
    this.primarySelectedId = numericId;
    this._updateEdgeHighlights();
    widget.emitEventSelectedSignal(numericId);
    widget.emitSelectedNodeIdsSignal(this.getSelectedIds());
  }

  selectMany(ids) {
    if (!this.cy) return;
    this.clearSelectionWithoutEmittingSignal();
    for (const id of ids) {
      const el = this.cy.getElementById(`${id}`);
      if (el && el.length) el.addClass('selected');
      this.selectedNodeIds.add(parseInt(id, 10));
    }
    this.primarySelectedId = ids.length ? parseInt(ids[0], 10) : null;
    this._updateEdgeHighlights();
    widget.emitEventSelectedSignal(this.getSelection());
    widget.emitSelectedNodeIdsSignal(this.getSelectedIds());
  }

  clearSelection() {
    this.clearSelectionWithoutEmittingSignal();
    widget.emitEventSelectedSignal(-1);
    widget.emitSelectedNodeIdsSignal([]);
  }

  clearSelectionWithoutEmittingSignal() {
    if (this.cy) {
      this.cy.nodes().removeClass('selected');
      this._clearEdgeHighlights();
    }
    this.selectedNodeIds.clear();
    this.primarySelectedId = null;
  }

  getSelection() {
    const ids = this.getSelectedIds();
    if (!ids.length) {
      this.primarySelectedId = null;
      return -1;
    }
    if (this.primarySelectedId == null || !ids.includes(parseInt(this.primarySelectedId, 10))) {
      this.primarySelectedId = ids[0];
    }
    return parseInt(this.primarySelectedId, 10);
  }

  getSelectedIds() {
    return [...this.selectedNodeIds]
      .filter((id) => !Number.isNaN(id))
      .sort((a, b) => a - b);
  }

  // ── Edge highlight helpers ──────────────────────────────────

  _clearEdgeHighlights() {
    if (!this.cy) return;
    this.cy.edges().removeClass('selected-in-edge selected-out-edge');
  }

  _updateEdgeHighlights() {
    this._clearEdgeHighlights();
    if (this.primarySelectedId == null || !this.cy) return;
    const node = this.cy.getElementById(`${this.primarySelectedId}`);
    if (!node || !node.length) {
      this.primarySelectedId = null;
      return;
    }
    node.incomers('edge').addClass('selected-in-edge');
    node.outgoers('edge').addClass('selected-out-edge');
  }

  // ── Viewport / scroll ───────────────────────────────────────

  getViewport() {
    if (!this.cy) return null;
    return {
      pan: { ...this.cy.pan() },
      zoom: this.cy.zoom(),
    };
  }

  restoreViewport(viewport) {
    if (!viewport || !this.cy) return;
    this.cy.viewport({ zoom: viewport.zoom, pan: viewport.pan });
  }

  viewportCenterPoint() {
    const el = document.getElementById('graph');
    if (!el) return { x: window.innerWidth / 2, y: window.innerHeight / 2 };
    const rect = el.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  }

  closestNodeIdToViewportCenter() {
    if (!this.cy) return null;
    const center = this.cy.extent();
    const cx = center.x1 + (center.x2 - center.x1) / 2;
    const cy2 = center.y1 + (center.y2 - center.y1) / 2;
    let closestId = null;
    let closestDist = Infinity;
    this.cy.nodes().forEach((node) => {
      const pos = node.position();
      const dx = pos.x - cx;
      const dy = pos.y - cy2;
      const dist = dx * dx + dy * dy;
      if (dist < closestDist) {
        closestDist = dist;
        closestId = node.id();
      }
    });
    return closestId == null ? null : parseInt(closestId, 10);
  }

  getElement(id) {
    if (!this.cy) return null;
    const el = this.cy.getElementById(`${id}`);
    return el && el.length ? el : null;
  }

  isElementVisible(id) {
    const el = this.getElement(id);
    if (!el) return false;
    const bb = el.renderedBoundingBox();
    const w = window.innerWidth;
    const h = window.innerHeight;
    const margin = 40;
    return bb.x2 >= margin && bb.y2 >= margin && bb.x1 <= w - margin && bb.y1 <= h - margin;
  }

  scrollTo(id, center = false, duration = 1000, targetScale = null) {
    if (!this.cy) return false;
    const el = this.getElement(id);
    if (!el) return false;

    const pos = el.position();
    const zoom = targetScale != null ? targetScale : this.cy.zoom();
    const container = document.getElementById('graph');
    const w = container ? container.clientWidth : window.innerWidth;
    const h = container ? container.clientHeight : window.innerHeight;
    const targetPan = {
      x: w / 2 - pos.x * zoom,
      y: center ? h / 2 - pos.y * zoom : 60 - pos.y * zoom,
    };

    if (duration > 0) {
      this.cy.animate({ zoom, pan: targetPan }, { duration });
    } else {
      this.cy.viewport({ zoom, pan: targetPan });
    }
    return true;
  }

  setScale(scale) {
    if (!this.cy) return;
    this.cy.zoom(scale);
  }

  setTranslate(pan) {
    if (!this.cy) return;
    // pan is [x, y] array (legacy API compat)
    this.cy.pan({ x: pan[0], y: pan[1] });
  }

  // Expose zoom-scale for the keyboard handler and profiler
  getZoom() {
    return this.cy ? this.cy.zoom() : 1;
  }

  getPan() {
    return this.cy ? this.cy.pan() : { x: 0, y: 0 };
  }
}

// ── Graph (data + layout coordinator) ───────────────────────

class Graph {
  constructor() {
    this.data = null;
    this._elements = [];      // raw Cytoscape element descriptors built from data
    this._nodeDataMap = {};   // id (string) → raw data entry
    this._edgeList = [];      // { source, target, virtual } — for context menu queries
    this.renderer = new Renderer();
    this.persistentComponentRootName = null;
  }

  // ── Data helpers for context menu ──────────────────────────

  getNodeData(id) {
    return this._nodeDataMap[`${id}`] || null;
  }

  getPrevNodes(id) {
    return [...new Set(
      this._edgeList
        .filter((e) => `${e.target}` === `${id}` && !e.virtual)
        .map((e) => parseInt(e.source, 10))
    )];
  }

  getNextNodes(id) {
    return [...new Set(
      this._edgeList
        .filter((e) => `${e.source}` === `${id}` && !e.virtual)
        .map((e) => parseInt(e.target, 10))
    )];
  }

  // Edge count for profiler (replaces g.edgeCount())
  edgeCount() {
    return this._edgeList.length;
  }

  // ── Build Cytoscape elements from data ──────────────────────

  update(data) {
    this.data = data;
    this._nodeDataMap = {};
    this._edgeList = [];
    this._elements = [];

    for (const entry of data) {
      if (entry.type === 'node') {
        this._nodeDataMap[`${entry.id}`] = entry;
        const rawLabel = getNodeLabel(entry);
        const label = getNodeLayoutLabel(rawLabel);
        const dimensions = computeNodeDimensions(label);
        const position = getNodePosition(entry);
        const nodeElement = {
          group: 'nodes',
          data: {
            id: `${entry.id}`,
            label,
            rawLabel,
            node_type: entry.node_type,
            name: entry.data.name,
            nodeWidth: dimensions.width,
            nodeHeight: dimensions.height,
          },
          classes: entry.node_type,
        };
        if (position) {
          nodeElement.position = position;
        }
        this._elements.push(nodeElement);
      } else if (entry.type === 'edge') {
        const edgeId = `edge-${entry.source}-${entry.target}-${entry.data.value}`;
        this._edgeList.push({ source: entry.source, target: entry.target, virtual: !!entry.data.virtual });
        this._elements.push({
          group: 'edges',
          data: {
            id: edgeId,
            source: `${entry.source}`,
            target: `${entry.target}`,
            label: entry.data.value == null ? '' : `${entry.data.value}`,
            virtual: !!entry.data.virtual,
          },
          classes: entry.data.virtual ? 'virtual' : '',
        });
      }
    }
  }

  updateLabels(data) {
    this.data = data;
    // Build a Map of node id → element index for O(1) lookups (replaces O(n) .find() per entry)
    const nodeElementMap = new Map();
    for (let i = 0; i < this._elements.length; i++) {
      const el = this._elements[i];
      if (el.group === 'nodes') {
        nodeElementMap.set(el.data.id, i);
      }
    }
    for (const entry of data) {
      if (entry.type === 'node') {
        const rawLabel = getNodeLabel(entry);
        const key = `${entry.id}`;
        // Update element descriptor in place via Map lookup — O(1)
        const idx = nodeElementMap.get(key);
        if (idx !== undefined) {
          const el = this._elements[idx];
          const label = getNodeLayoutLabel(rawLabel);
          const dimensions = computeNodeDimensions(label);
          el.data.label = label;
          el.data.rawLabel = rawLabel;
          el.data.nodeWidth = dimensions.width;
          el.data.nodeHeight = dimensions.height;
        }
        // Update node data map
        this._nodeDataMap[key] = entry;
      }
    }
  }

  refresh() {
    if (this.data && this.data.length > 0) {
      this.update(this.data);
    }
  }

  render(transitionMs = GRAPH_TRANSITION_MS) {
    const tStart = performance.now();
    lastUpdatePath = 'Full Layout';

    if (this.hasPersistentComponentFilter()) {
      const componentIds = this.findPersistentComponentIds();
      if (componentIds) {
        this.renderer.nodeWhitelist = componentIds;
      } else {
        this.clearPersistentComponentFilter();
        this.renderer.nodeWhitelist = null;
      }
    } else {
      this.renderer.nodeWhitelist = null;
    }

    this.renderer.render(this._elements, transitionMs);
    refreshGraphSearch(false);

    const tEnd = performance.now();
    lastLayoutTime = tEnd - tStart;
    lastUpdateTime = 0;
  }

  // ── Component filter ─────────────────────────────────────────

  hasPersistentComponentFilter() {
    return !!this.persistentComponentRootName;
  }

  clearPersistentComponentFilter() {
    this.persistentComponentRootName = null;
  }

  _findNodeIdByName(name) {
    if (name == null) return null;
    for (const [id, entry] of Object.entries(this._nodeDataMap)) {
      if (entry && entry.data && entry.data.name === name) return id;
    }
    return null;
  }

  findNodeComponentIds(v) {
    // Use Cytoscape's built-in connected components via BFS.
    if (!this.renderer.cy) return null;
    const startNode = this.renderer.cy.getElementById(`${v}`);
    if (!startNode || !startNode.length) return null;

    // Collect all nodes in the same connected component (undirected).
    const visited = new Set();
    const queue = [startNode];
    while (queue.length) {
      const current = queue.pop();
      const cid = current.id();
      if (visited.has(cid)) continue;
      visited.add(cid);
      // Walk both incomers and outgoers (treat graph as undirected for component)
      current.connectedEdges().connectedNodes().forEach((n) => {
        if (!visited.has(n.id())) queue.push(n);
      });
    }
    return visited.size ? visited : null;
  }

  findPersistentComponentIds() {
    const rootId = this._findNodeIdByName(this.persistentComponentRootName);
    if (rootId == null) return null;
    return this.findNodeComponentIds(rootId);
  }

  renderOnlyConnected(v) {
    const selected = this.renderer.getSelection();
    if (v == null) {
      this.clearPersistentComponentFilter();
    } else {
      const nodeData = this.getNodeData(v);
      this.persistentComponentRootName = nodeData && nodeData.data ? nodeData.data.name : null;
    }
    this.render();
    if (v != null && this.renderer.getElement(v)) {
      setTimeout(() => this.renderer.scrollTo(v), 500);
    } else if (selected !== -1 && this.renderer.getElement(selected)) {
      setTimeout(() => this.renderer.scrollTo(selected), 500);
    }
  }

  selectConnected(v) {
    const component = this.findNodeComponentIds(v);
    if (!component) return;
    const ids = [...component]
      .map((nodeId) => parseInt(nodeId, 10))
      .filter((nodeId) => !Number.isNaN(nodeId) && nodeId >= 0);
    this.renderer.selectMany(ids);
  }
}

graph = new Graph();

// ── Search (data-only — unchanged logic, Cytoscape API for highlights) ──

function pushNodeParams(parts, node) {
  if (!node || !node.data || !node.data.params) return;
  try { parts.push(JSON.stringify(node.data.params)); } catch (err) {}
}

function pushNodeIdentity(parts, node) {
  if (!node || !node.data) return;
  if (node.data.name)   parts.push(node.data.name);
  if (node.data.actor)  parts.push(node.data.actor);
  if (node.data.action) parts.push(node.data.action);
  if (node.data.query)  parts.push(node.data.query);
}

function pushMalsText(parts, node) {
  if (!node || !node.data) return;
  if (node.data._message_text) parts.push(node.data._message_text);
  if (node.data._choice_label_texts) {
    for (const value of Object.values(node.data._choice_label_texts)) {
      parts.push(value);
    }
  }
}

function getSearchableNodeText(node, scope = 'all') {
  if (!node || !node.data) return '';
  const parts = [];
  if (scope === 'mals') { pushMalsText(parts, node); return parts.join('\n'); }
  if (scope === 'params') { pushNodeParams(parts, node); return parts.join('\n'); }
  if (scope === 'events') { pushNodeIdentity(parts, node); return parts.join('\n'); }
  if (scope === 'switches') {
    if (node.node_type !== 'switch') return '';
    pushNodeIdentity(parts, node); pushNodeParams(parts, node);
    return parts.join('\n');
  }
  if (scope === 'subflows') {
    if (node.node_type !== 'sub_flow') return '';
    pushNodeIdentity(parts, node);
    if (node.data.entry_point_name) parts.push(node.data.entry_point_name);
    if (node.data.res_flowchart_name) parts.push(node.data.res_flowchart_name);
    pushNodeParams(parts, node);
    return parts.join('\n');
  }
  pushNodeIdentity(parts, node);
  pushNodeParams(parts, node);
  pushMalsText(parts, node);
  if (node.data.entry_point_name) parts.push(node.data.entry_point_name);
  if (node.data.res_flowchart_name) parts.push(node.data.res_flowchart_name);
  return parts.join('\n');
}

function clearSearchHighlightClasses() {
  if (!graph || !graph.renderer.cy) return;
  graph.renderer.cy.nodes().removeClass('search-match search-current');
}

function applySearchHighlights() {
  clearSearchHighlightClasses();
  if (!graphSearchMatches.length || !graph || !graph.renderer.cy) return;

  for (const nodeId of graphSearchMatches) {
    const el = graph.renderer.getElement(nodeId);
    if (el) el.addClass('search-match');
  }

  if (graphSearchIndex >= 0 && graphSearchIndex < graphSearchMatches.length) {
    const currentEl = graph.renderer.getElement(graphSearchMatches[graphSearchIndex]);
    if (currentEl) currentEl.addClass('search-current');
  }
}

function emitSearchResults() {
  if (!widget || !widget.emitSearchResultsSignal) return;
  widget.emitSearchResultsSignal(graphSearchMatches.length, graphSearchIndex);
}

function scrollToCurrentSearchResult(duration = 500) {
  if (graphSearchIndex < 0 || graphSearchIndex >= graphSearchMatches.length) return;
  const targetId = graphSearchMatches[graphSearchIndex];
  graph.renderer.select(targetId, false);
  graph.renderer.scrollTo(targetId, true, duration, 1);
}

function refreshGraphSearch(scrollToResult) {
  const previousCurrentId =
    graphSearchIndex >= 0 && graphSearchIndex < graphSearchMatches.length
      ? graphSearchMatches[graphSearchIndex]
      : null;

  if (!graphSearchQuery || !graph || !graph.data) {
    graphSearchMatches = [];
    graphSearchIndex = -1;
    applySearchHighlights();
    emitSearchResults();
    return;
  }

  const normalizedNeedle = graphSearchCaseInsensitive ? graphSearchQuery.toLowerCase() : graphSearchQuery;
  graphSearchMatches = graph.data
    .filter((entry) => entry.type === 'node')
    .filter((entry) => {
      const haystack = getSearchableNodeText(entry, graphSearchScope);
      if (!haystack) return false;
      const normalizedHaystack = graphSearchCaseInsensitive ? haystack.toLowerCase() : haystack;
      return normalizedHaystack.includes(normalizedNeedle);
    })
    .map((entry) => parseInt(entry.id, 10))
    .filter((entryId) => !Number.isNaN(entryId));

  if (!graphSearchMatches.length) {
    graphSearchIndex = -1;
    applySearchHighlights();
    emitSearchResults();
    return;
  }

  if (previousCurrentId != null) {
    const existingIndex = graphSearchMatches.indexOf(previousCurrentId);
    graphSearchIndex = existingIndex >= 0 ? existingIndex : 0;
  } else if (graphSearchIndex < 0 || graphSearchIndex >= graphSearchMatches.length) {
    graphSearchIndex = 0;
  }

  applySearchHighlights();
  emitSearchResults();
  if (scrollToResult) scrollToCurrentSearchResult();
}

// ── Exported API (window.eventEditorSet* — unchanged names) ──

window.eventEditorSetSearchQuery = function (query, caseInsensitive, scrollToResult, scope = 'all') {
  graphSearchQuery = (query || '').trim();
  graphSearchCaseInsensitive = !!caseInsensitive;
  graphSearchScope = ['all', 'mals', 'params', 'events', 'switches', 'subflows'].includes(scope) ? scope : 'all';
  refreshGraphSearch(!!scrollToResult);
};

window.eventEditorSetRenderMessageTagsAsStyling = function (enabled) {
  renderMessageTagsAsStyling = !!enabled;
};

window.eventEditorSetShowNonTextMessageTags = function (visible) {
  showNonTextMessageTags = !!visible;
};

window.eventEditorSetIncludeMessageBlankLines = function (include) {
  includeMessageBlankLines = !!include;
};

window.eventEditorSetShowMessageBubbleBreaks = function (show) {
  showMessageBubbleBreaks = !!show;
};

window.eventEditorStepSearch = function (delta) {
  if (!graphSearchMatches.length) { emitSearchResults(); return; }
  const offset = delta < 0 ? -1 : 1;
  graphSearchIndex = (graphSearchIndex + offset + graphSearchMatches.length) % graphSearchMatches.length;
  applySearchHighlights();
  emitSearchResults();
  scrollToCurrentSearchResult(350);
};

window.eventEditorSetSearchIndex = function (index) {
  if (!graphSearchMatches.length) { emitSearchResults(); return; }
  const clampedIndex = Math.max(0, Math.min(graphSearchMatches.length - 1, parseInt(index, 10) || 0));
  graphSearchIndex = clampedIndex;
  applySearchHighlights();
  emitSearchResults();
  scrollToCurrentSearchResult(350);
};

// ── Keyboard handling ────────────────────────────────────────

document.body.addEventListener('keydown', (event) => {
  const key = event.key;

  if (key === 'Escape') {
    graph.renderer.clearSelection();
    return;
  }

  // Ctrl+ArrowUp/Down → zoom
  if (event.ctrlKey) {
    let scaleMultiplier = 1;
    if (key === 'ArrowUp') scaleMultiplier = 1.1;
    else if (key === 'ArrowDown') scaleMultiplier = 0.9;
    graph.renderer.setScale(graph.renderer.getZoom() * scaleMultiplier);
    if (scaleMultiplier !== 1) return;
  }

  const selected = graph.renderer.getSelection();
  if (selected === -1) {
    // No selection — pan with arrow keys
    let vDir = 0, hDir = 0;
    switch (key) {
      case 'ArrowUp':    vDir = 1;  break;
      case 'ArrowDown':  vDir = -1; break;
      case 'ArrowLeft':  hDir = 1;  break;
      case 'ArrowRight': hDir = -1; break;
    }
    const pan = graph.renderer.getPan();
    graph.renderer.setTranslate([pan.x + 100 * hDir, pan.y + 100 * vDir]);
    return;
  }

  // Arrow navigate between connected nodes
  if (key === 'ArrowUp' || key === 'ArrowDown') {
    const cy = graph.renderer.cy;
    if (!cy) return;
    const node = cy.getElementById(`${selected}`);
    if (!node || !node.length) return;
    const neighbors = key === 'ArrowUp'
      ? node.incomers('node')
      : node.outgoers('node');
    if (neighbors.length > 0) {
      const nextId = neighbors[0].id();
      graph.renderer.scrollTo(nextId, true, 500);
      graph.renderer.select(nextId);
    }
  }
});

// ── QWebChannel bootstrap ────────────────────────────────────

function rerenderAroundCurrentNode(preferredNodeId) {
  const currentViewport = graph.renderer.getViewport();
  const targetNodeId = preferredNodeId != null ? preferredNodeId : graph.renderer.getSelection();
  graph.refresh();
  graph.render(0);
  setTimeout(() => {
    if (targetNodeId != null && targetNodeId !== -1 && graph.renderer.getElement(targetNodeId)) {
      graph.renderer.scrollTo(targetNodeId, true, 0);
    } else {
      graph.renderer.restoreViewport(currentViewport);
    }
  }, 20);
}

new QWebChannel(qt.webChannelTransport, (channel) => {
  widget = channel.objects.widget;

  function select(id) {
    if (graph.hasPersistentComponentFilter()) {
      graph.renderOnlyConnected(id);
      graph.renderer.select(id);
    } else {
      graph.renderer.select(id);
      graph.renderer.scrollTo(id);
    }
  }

  function reveal(id) {
    if (graph.hasPersistentComponentFilter() && !graph.renderer.getElement(id)) {
      graph.clearPersistentComponentFilter();
      graph.render();
    }
    graph.renderer.select(id);
    graph.renderer.scrollTo(id, true, 500);
  }

  function checkCanFastUpdate(newData) {
    if (!graph.data || !graph._elements.length) return false;
    if (newData.length !== graph.data.length) return false;

    const oldNodes = {};
    const oldEdges = {};
    for (const entry of graph.data) {
      if (entry.type === 'node') oldNodes[entry.id] = entry;
      else if (entry.type === 'edge') oldEdges[`${entry.source}-${entry.target}-${entry.data.value}`] = entry;
    }

    for (const entry of newData) {
      if (entry.type === 'node') {
        const oldNode = oldNodes[entry.id];
        if (!oldNode) return false;
        if (entry.node_type !== oldNode.node_type) return false;
        if (entry.data.name !== oldNode.data.name ||
          entry.data.actor !== oldNode.data.actor ||
          entry.data.action !== oldNode.data.action ||
          entry.data.query !== oldNode.data.query ||
          entry.data.res_flowchart_name !== oldNode.data.res_flowchart_name ||
          entry.data.entry_point_name !== oldNode.data.entry_point_name) {
          return false;
        }
        const oldParamsCount = oldNode.data.params ? Object.keys(oldNode.data.params).length : 0;
        const newParamsCount = entry.data.params ? Object.keys(entry.data.params).length : 0;
        if (oldParamsCount !== newParamsCount) return false;
        if (newParamsCount > 0) {
          const oldKeys = Object.keys(oldNode.data.params).sort().join(',');
          const newKeys = Object.keys(entry.data.params).sort().join(',');
          if (oldKeys !== newKeys) return false;
        }
        const oldRawLabel = getNodeLabel(oldNode);
        const newRawLabel = getNodeLabel(entry);
        if (oldRawLabel.split('\n').length !== newRawLabel.split('\n').length) return false;
      } else if (entry.type === 'edge') {
        const edgeKey = `${entry.source}-${entry.target}-${entry.data.value}`;
        if (!oldEdges[edgeKey]) return false;
      }
    }
    return true;
  }

  function load(cb) {
    const loadToken = ++pendingLoadFinalizeToken;
    widget.getJson((data) => {
      if (!data) return;
      const transitionMs = nextGraphTransitionMs;
      nextGraphTransitionMs = GRAPH_TRANSITION_MS;
      const isFastUpdate = !resetViewportOnNextLoad && checkCanFastUpdate(data);
      let activeTransitionMs = transitionMs;

      if (isFastUpdate) {
        graph.updateLabels(data);
        graph.renderer.fastUpdate(graph._elements);
        activeTransitionMs = 0;
      } else {
        graph.update(data);
        graph.render(transitionMs);
      }

      const finalizeLoad = () => {
        if (loadToken !== pendingLoadFinalizeToken) return;
        if (preservedViewport && !resetViewportOnNextLoad) {
          graph.renderer.restoreViewport(preservedViewport);
          if (preservedFocusNodeId != null) {
            const focusedEl = graph.renderer.getElement(preservedFocusNodeId);
            if (focusedEl && preservedFocusPoint) {
              // Adjust pan so the focus node stays at the same screen position
              const cy = graph.renderer.cy;
              if (cy) {
                const pos = focusedEl.renderedPosition();
                const dx = preservedFocusPoint.x - pos.x;
                const dy = preservedFocusPoint.y - pos.y;
                const pan = cy.pan();
                cy.pan({ x: pan.x + dx, y: pan.y + dy });
              }
            }
          }
        }
        if (resetViewportOnNextLoad) {
          graph.renderer.setTranslate([20, 20]);
          resetViewportOnNextLoad = false;
        }
        widget.emitReloadedSignal();
        if (cb) cb(data);
        isDeleting = false;
        suppressNextViewportAdjustment = false;
        preservedViewport = null;
        preservedFocusNodeId = null;
        preservedFocusPoint = null;
      };

      setTimeout(finalizeLoad, activeTransitionMs + 20);
    });
  }

  widget.flowDataChanged.connect(() => { load(); });

  widget.fileLoaded.connect(() => {
    graph.clearPersistentComponentFilter();
    graph.renderer.clearSelection();
    preservedViewport = null;
    resetViewportOnNextLoad = true;
  });

  widget.selectRequested.connect((id) => { select(id); });
  widget.revealRequested.connect((id) => { reveal(id); });

  widget.instantRevealRequested.connect((id) => {
    if (graph.hasPersistentComponentFilter() && !graph.renderer.getElement(id)) {
      graph.clearPersistentComponentFilter();
      graph.render(0);
    }
    graph.renderer.select(id);
    graph.renderer.scrollTo(id, true, 0);
  });

  widget.preserveViewportRequested.connect(() => {
    preservedViewport = graph.renderer.getViewport();
    preservedFocusNodeId = graph.renderer.closestNodeIdToViewportCenter();
    if (preservedFocusNodeId != null) {
      const el = graph.renderer.getElement(preservedFocusNodeId);
      preservedFocusPoint = el ? el.renderedPosition() : null;
    } else {
      preservedFocusPoint = null;
    }
    suppressNextViewportAdjustment = true;
  });

  widget.fastGraphReloadRequested.connect(() => { nextGraphTransitionMs = 0; });

  widget.eventNameVisibilityChanged.connect((visible) => { eventNamesVisible = visible; });
  widget.eventParamVisibilityChanged.connect((visible) => { eventParamVisible = visible; });
  widget.eventMessageVisibilityChanged.connect((visible) => { eventMessagesVisible = visible; });
  widget.actionProhibitionChanged.connect((value) => { actionsProhibited = value; });
  widget.entryPointFilterStateChanged.connect((value) => { hasHiddenEntryPoints = !!value; });

  widget.emitReadySignal();
  load();
  if (SHOW_PROFILER) {
    initProfiler();
  }
});

// ── Graphics renderer detection (unchanged) ──────────────────

let rendererInfo = null;

function getGraphicsRenderer() {
  if (rendererInfo) return rendererInfo;
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if (!gl) { rendererInfo = 'Software (No WebGL)'; return rendererInfo; }
    const dbgRenderInfo = gl.getExtension('WEBGL_debug_renderer_info');
    if (dbgRenderInfo) {
      const renderer = gl.getParameter(dbgRenderInfo.UNMASKED_RENDERER_WEBGL) || '';
      const lower = renderer.toLowerCase();
      if (lower.includes('swiftshader') || lower.includes('llvmpipe') || lower.includes('software')) {
        rendererInfo = 'Software (' + renderer.split(' vs_')[0].split(' Direct3D')[0] + ')';
      } else {
        rendererInfo = 'GPU (' + renderer.replace(/^ANGLE \((.*)\)$/, '$1').split(' Direct3D')[0] + ')';
      }
    } else {
      rendererInfo = 'GPU (WebGL Active)';
    }
  } catch (e) {
    rendererInfo = 'Unknown';
  }
  return rendererInfo;
}

// ── Profiler HUD ─────────────────────────────────────────────

function initProfiler() {
  fpsContainer = document.createElement('div');
  fpsContainer.className = 'profiler-hud';
  document.body.appendChild(fpsContainer);
  requestAnimationFrame(profileLoop);
}

function profileLoop() {
  const now = performance.now();
  frameCount++;

  if (now - lastFpsUpdate >= 500) {
    currentFps = Math.round((frameCount * 1000) / (now - lastFpsUpdate));
    frameCount = 0;
    lastFpsUpdate = now;

    if (currentFps < minFps && currentFps > 0) minFps = currentFps;
    if (currentFps > maxFps) maxFps = currentFps;

    const avgCpu = cpuTimeHistory.length
      ? (cpuTimeHistory.reduce((a, b) => a + b, 0) / cpuTimeHistory.length).toFixed(2)
      : '0.00';
    cpuTimeHistory = [];

    if (fpsContainer && graph) {
      const cy = graph.renderer.cy;
      const scale = cy ? cy.zoom() : 1.0;
      const totalNodes = cy ? cy.nodes().length : 0;
      const totalEdges = graph.edgeCount();

      const renderer = getGraphicsRenderer();
      const isGPU = renderer.startsWith('GPU');
      const hwAcc = isGPU ? 'Enabled (GPU)' : 'Disabled (CPU)';
      const lastOpTime = lastUpdatePath === 'Fast In-Place'
        ? `${lastUpdateTime.toFixed(1)} ms`
        : `${lastLayoutTime.toFixed(1)} ms`;

      // Cytoscape canvas doesn't have a DOM node count per se; report canvas elements
      const domCount = cy ? cy.nodes().length + cy.edges().length : 0;

      fpsContainer.innerHTML =
        `<div class="profiler-hud-header">Performance Profiler</div>` +
        `<div class="profiler-hud-row"><span class="profiler-hud-label">FPS</span><span class="profiler-hud-val">${currentFps} (Min: ${minFps === 1000 ? 0 : minFps} / Max: ${maxFps})</span></div>` +
        `<div class="profiler-hud-row"><span class="profiler-hud-label">Hardware Accel</span><span class="profiler-hud-val" style="color: ${isGPU ? '#4caf50' : '#f44336'}">${hwAcc}</span></div>` +
        `<div class="profiler-hud-row"><span class="profiler-hud-label">Graphics Engine</span><span class="profiler-hud-val">${renderer}</span></div>` +
        `<div class="profiler-hud-row"><span class="profiler-hud-label">Pan/Zoom CPU</span><span class="profiler-hud-val">${avgCpu} ms</span></div>` +
        `<div class="profiler-hud-row"><span class="profiler-hud-label">Last Render Path</span><span class="profiler-hud-val">${lastUpdatePath}</span></div>` +
        `<div class="profiler-hud-row"><span class="profiler-hud-label">Last Render Time</span><span class="profiler-hud-val">${lastOpTime}</span></div>` +
        `<div class="profiler-hud-row"><span class="profiler-hud-label">Viewport Scale</span><span class="profiler-hud-val">${scale.toFixed(2)}x</span></div>` +
        `<div class="profiler-hud-row"><span class="profiler-hud-label">Total Nodes</span><span class="profiler-hud-val">${totalNodes}</span></div>` +
        `<div class="profiler-hud-row"><span class="profiler-hud-label">Total Edges</span><span class="profiler-hud-val">${totalEdges}</span></div>` +
        `<div class="profiler-hud-row"><span class="profiler-hud-label">Canvas Elements</span><span class="profiler-hud-val">${domCount} nodes+edges</span></div>`;

      if (currentFps < 30) fpsContainer.style.borderColor = '#ff3333';
      else if (currentFps < 50) fpsContainer.style.borderColor = '#ffcc00';
      else fpsContainer.style.borderColor = '';
    }
  }

  requestAnimationFrame(profileLoop);
}