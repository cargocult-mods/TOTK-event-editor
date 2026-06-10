let graph;
let widget;
let eventNamesVisible = false;
let eventParamVisible = false;
let eventMessagesVisible = false;
let actionsProhibited = false;
let isDeleting = false;
let suppressNextViewportAdjustment = false;
let hasHiddenEntryPoints = false;
let resetViewportOnNextLoad = true;
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
const GRAPH_FIT_PADDING = 40;
const GRAPH_FIT_MAX_SCALE = 1;
const READABLE_NODE_SCALE = 1;
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

function isMultiSelectEvent(event) {
  return !!(event && (event.ctrlKey || event.metaKey));
}

function formatNodeParamValue(value, key=null) {
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

function wrapLabelText(text, maxLength=LABEL_WRAP_LENGTH) {
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

function appendWrappedLabelLineWithIndent(label, prefix, text, continuationPrefix='  ') {
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

function getElementCenterInViewport(element) {
  if (!element || !element.node()) {
    return null;
  }
  const rect = element.node().getBoundingClientRect();
  return {
    x: rect.left + (rect.width / 2),
    y: rect.top + (rect.height / 2),
  };
}

function rerenderAroundCurrentNode(preferredNodeId) {
  const currentViewport = graph.renderer.getViewport();
  const targetNodeId = preferredNodeId != null ? preferredNodeId : graph.renderer.getSelection();
    graph.refresh();
  graph.render(0);
  setTimeout(() => {
    if (targetNodeId != null && targetNodeId !== -1 && graph.renderer.getElement(targetNodeId)) {
      graph.renderer.scrollTo(targetNodeId, true, 0, READABLE_NODE_SCALE);
    } else {
      graph.renderer.restoreViewport(currentViewport);
    }
  }, 20);
}

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

function handleNodeContextMenu(id) {
  const actions = [];
  const selectedNodeIds = graph.renderer.getSelectedIds();
  const selectedCount = selectedNodeIds.length;

  const idx = parseInt(id, 10);
  const node = graph.g.node(id);
  const prevNodes = [...(new Set(graph.g.inEdges(id).filter(e => !graph.g.edge(e).virtual).map(e => parseInt(e.v, 10))))];
  const nextNodes = [...(new Set(graph.g.outEdges(id).filter(e => !graph.g.edge(e).virtual).map(e => parseInt(e.w, 10))))];
  const classes = node.class.split(' ');

  const addAction = (name, fn) => actions.push({ title: name, action: () => { setTimeout(fn, 60) } });
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
  const addAction = (name, fn) => actions.push({ title: name, action: () => { setTimeout(fn, 60) } });
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

function clampContextMenuToViewport() {
  const menuNode = d3.select('.d3-context-menu').node();
  if (!menuNode) {
    return;
  }
  const rect = menuNode.getBoundingClientRect();
  const maxLeft = Math.max(8, window.innerWidth - rect.width - 8);
  const maxTop = Math.max(8, window.innerHeight - rect.height - 8);
  const left = Math.max(8, Math.min(rect.left, maxLeft));
  const top = Math.max(8, Math.min(rect.top, maxTop));
  d3.select('.d3-context-menu')
    .style('left', `${left}px`)
    .style('top', `${top}px`);
}

class Renderer {
  constructor() {
    this.svg = d3.select('svg');
    this.svgGroup = d3.select('svg g');
    this.selectedNodeIds = new Set();
    this.primarySelectedId = null;

    this.nodeWhitelist = null;

    this.zoom = d3.behavior.zoom();
    this.lastZoomEventStart = null;
    this.svg.call(this.zoom.on('zoom', () => this.updateTransform()));
    this.svg.call(this.zoom.on('zoomstart', () => this.lastZoomEventStart = new Date()));

    // Reset selection on click.
    // Unfortunately we need to do some extra work to determine whether the click event is caused
    // by zooming or is a simple click.
    this.svg.on('click', () => {
      // The zoom lasted more than 100 ms, so it's likely a zoom.
      if ((new Date() - this.lastZoomEventStart) >= 100) {
        return;
      }
      this.clearSelection();
    });
    this.svg.on('contextmenu', () => {
      if (this._isTargetInsideNode(d3.event.target)) {
        return;
      }
      d3.contextMenu(handleBackgroundContextMenu).call(this.svg.node());
      clampContextMenuToViewport();
    });
  }

  _restoreRawNodeLabels(visibleGraph) {
    this.svgGroup.selectAll('.node').each(function(id) {
      const node = visibleGraph.node(id);
      const rawLabel = node && node.rawLabel;
      if (typeof rawLabel !== 'string') {
        return;
      }

      const rawLines = rawLabel.split('\n');
      const tspans = this.querySelectorAll('.label text tspan');
      if (rawLines.length !== tspans.length) {
        return;
      }
      rawLines.forEach((line, index) => {
        tspans[index].textContent = line;
      });
    });
  }

  _styleMessageTags() {
    this.svgGroup.selectAll('.node .label text').each(function() {
      const textNode = this;
      const tspans = textNode.querySelectorAll('tspan');
      const currentStyle = {};
      tspans.forEach((lineTspan) => {
        const line = lineTspan.textContent || '';
        if (line === MESSAGE_BLANK_LINE || line === MESSAGE_BUBBLE_BREAK_LINE) {
          lineTspan.textContent = MESSAGE_BLANK_LINE;
          lineTspan.setAttribute('fill-opacity', '0');
          lineTspan.setAttribute('class', line === MESSAGE_BUBBLE_BREAK_LINE ? 'message-bubble-break' : 'message-blank-line');
          if (line === MESSAGE_BUBBLE_BREAK_LINE) {
            lineTspan.setAttribute('font-size', '7px');
          }
          return;
        }
        if (!MESSAGE_TAG_REGEX.test(line)) {
          MESSAGE_TAG_REGEX.lastIndex = 0;
          if (renderMessageTagsAsStyling && hasSvgTextStyle(currentStyle)) {
            applySvgTextStyle(lineTspan, currentStyle);
          }
          return;
        }
        MESSAGE_TAG_REGEX.lastIndex = 0;
        const parts = line.split(MESSAGE_TAG_REGEX).filter((part) => part.length > 0);
        while (lineTspan.firstChild) {
          lineTspan.removeChild(lineTspan.firstChild);
        }
        for (const part of parts) {
          const segment = document.createElementNS('http://www.w3.org/2000/svg', 'tspan');
          if (/^\{\{[^{}\n]+\}\}$/.test(part)) {
            const tag = parseMessageTag(part);
            segment.textContent = isMessageTagHidden(tag) ? '' :
              (renderMessageTagsAsStyling ? formatMessageTagPreview(tag) : part);
            segment.setAttribute('class', `message-tag message-tag-${tag.name.replace(/[^A-Za-z0-9_-]/g, '-')}`);
            const markerStyle = renderMessageTagsAsStyling
              ? mutateMessageTextStyleForTag(tag, currentStyle)
              : { fill: '#b8bcc4' };
            applySvgTextStyle(segment, markerStyle);
          } else {
            segment.textContent = part;
            if (renderMessageTagsAsStyling) {
              applySvgTextStyle(segment, currentStyle);
            }
          }
          if (segment.textContent) {
            lineTspan.appendChild(segment);
          }
        }
      });
    });
  }

  _fitNodeBoxesToLabels() {
    this.svgGroup.selectAll('.node').each(function() {
      const shape = this.firstElementChild;
      const label = this.querySelector('.label');
      if (!shape || !label || shape.tagName.toLowerCase() !== 'rect') {
        return;
      }

      let bbox;
      try {
        bbox = label.getBBox();
      } catch (error) {
        return;
      }
      if (!bbox || bbox.width <= 0 || bbox.height <= 0) {
        return;
      }

      const padX = 10;
      const padY = 8;
      const currentX = parseFloat(shape.getAttribute('x')) || 0;
      const currentY = parseFloat(shape.getAttribute('y')) || 0;
      const currentWidth = parseFloat(shape.getAttribute('width')) || 0;
      const currentHeight = parseFloat(shape.getAttribute('height')) || 0;
      const centerX = currentX + (currentWidth / 2);
      const centerY = currentY + (currentHeight / 2);
      const fittedWidth = Math.ceil(bbox.width + (padX * 2));
      const fittedHeight = Math.ceil(bbox.height + (padY * 2));
      const nextWidth = Math.max(currentWidth, fittedWidth);
      const nextHeight = Math.max(currentHeight, fittedHeight);
      shape.setAttribute('x', `${Math.floor(centerX - (nextWidth / 2))}`);
      shape.setAttribute('y', `${Math.floor(centerY - (nextHeight / 2))}`);
      shape.setAttribute('width', `${nextWidth}`);
      shape.setAttribute('height', `${nextHeight}`);
    });
  }

  getSelection() {
    const selectedIds = this.getSelectedIds();
    if (!selectedIds.length) {
      this.primarySelectedId = null;
      return -1;
    }

    if (this.primarySelectedId == null || !selectedIds.includes(parseInt(this.primarySelectedId, 10))) {
      this.primarySelectedId = selectedIds[0];
    }
    return parseInt(this.primarySelectedId, 10);
  }

  getSelectedIds() {
    const domIds = this._getSelectedIdsFromDom();
    if (domIds.length || this.selectedNodeIds.size === 0) {
      this.selectedNodeIds = new Set(domIds);
      if (this.primarySelectedId != null && !this.selectedNodeIds.has(this.primarySelectedId)) {
        this.primarySelectedId = domIds.length ? domIds[domIds.length - 1] : null;
      }
      return domIds;
    }

    return [...this.selectedNodeIds]
      .filter((id) => !Number.isNaN(id))
      .sort((a, b) => a - b);
  }

  _getSelectedIdsFromDom() {
    const selectedIds = [];
    this.svgGroup.selectAll('.node.selected').each(function(id) {
      let numericId = parseInt(id, 10);
      if (Number.isNaN(numericId)) {
        const elementId = d3.select(this).attr('id');
        if (elementId && elementId.startsWith('n')) {
          numericId = parseInt(elementId.substring(1), 10);
        }
      }
      if (!Number.isNaN(numericId)) {
        selectedIds.push(numericId);
      }
    });
    return [...new Set(selectedIds)].sort((a, b) => a - b);
  }

  clearSelection() {
    this.clearSelectionWithoutEmittingSignal();
    widget.emitEventSelectedSignal(-1);
    widget.emitSelectedNodeIdsSignal([]);
  }

  clearSelectionWithoutEmittingSignal() {
    const selectedIds = this.getSelectedIds();
    for (const cl of ['selected', 'selected-in-edge', 'selected-out-edge', 'selected-in-edge-label', 'selected-out-edge-label']) {
      d3.selectAll('.' + cl).classed(cl, false);
    }
    this.selectedNodeIds.clear();
    this.primarySelectedId = null;
    if (!graph.g) {
      return;
    }
    for (const nodeId of selectedIds) {
      this._updateNodeSelectionClass(nodeId, graph.g, false);
    }
  }

  _isTargetInsideNode(target) {
    while (target) {
      if (target.classList && target.classList.contains('node')) {
        return true;
      }
      if (target === this.svg.node()) {
        break;
      }
      target = target.parentNode;
    }
    return false;
  }

  _resolveNodeId(g, id) {
    if (!g) {
      return id;
    }
    if (g.node(id)) {
      return id;
    }
    const numericId = parseInt(id, 10);
    if (!Number.isNaN(numericId) && g.node(numericId)) {
      return numericId;
    }
    const stringId = `${id}`;
    if (g.node(stringId)) {
      return stringId;
    }
    return id;
  }

  _updateNodeSelectionClass(id, g, selected) {
    const resolvedId = this._resolveNodeId(g, id);
    const node = g.node(resolvedId);
    if (!node) {
      return;
    }
    const cleanedClass = node.class.replace(/\bselected\b/g, '').replace(/\s+/g, ' ').trim();
    node.class = selected ? `${cleanedClass} selected`.trim() : cleanedClass;
    d3.select(`#n${resolvedId}`).classed('selected', selected);
  }

  _updateEdgeHighlights(g) {
    for (const cl of ['selected-in-edge', 'selected-out-edge', 'selected-in-edge-label', 'selected-out-edge-label']) {
      d3.selectAll('.' + cl).classed(cl, false);
    }

    if (this.primarySelectedId == null) {
      return;
    }

    const id = this._resolveNodeId(g, this.primarySelectedId);
    if (!g.node(id)) {
      this.primarySelectedId = null;
      return;
    }

    g.inEdges(id).forEach((e) => {
      d3.selectAll(`.edge-${e.v}-${e.w}`).classed('selected-in-edge', true);
      d3.select(`#label-${e.name}`).classed('selected-in-edge-label', true);
    });
    g.outEdges(id).forEach((e) => {
      d3.selectAll(`.edge-${e.v}-${e.w}`).classed('selected-out-edge', true);
      d3.select(`#label-${e.name}`).classed('selected-out-edge-label', true);
    });
  }

  _refreshPrimarySelection(g) {
    const selectedIds = this.getSelectedIds()
      .filter((id) => !!g.node(this._resolveNodeId(g, id)));
    this.selectedNodeIds = new Set(selectedIds);
    if (!selectedIds.length) {
      this.primarySelectedId = null;
      this._updateEdgeHighlights(g);
      return;
    }

    if (this.primarySelectedId == null || !selectedIds.includes(parseInt(this.primarySelectedId, 10))) {
      this.primarySelectedId = selectedIds[0];
    }
    this._updateEdgeHighlights(g);
  }

  select(id, g, emitSignal=true) {
    const resolvedId = this._resolveNodeId(g, id);
    const numericId = parseInt(resolvedId, 10);
    this.clearSelectionWithoutEmittingSignal();
    this._updateNodeSelectionClass(resolvedId, g, true);
    this.selectedNodeIds.add(numericId);
    this.primarySelectedId = numericId;
    this._updateEdgeHighlights(g);
    if (emitSignal) {
      widget.emitEventSelectedSignal(numericId);
      widget.emitSelectedNodeIdsSignal(this.getSelectedIds());
    }
  }

  toggleSelection(id, g) {
    const resolvedId = this._resolveNodeId(g, id);
    const numericId = parseInt(resolvedId, 10);
    const element = this.getElement(resolvedId);
    if (!element) {
      return;
    }

    if (element.classed('selected')) {
      this._updateNodeSelectionClass(resolvedId, g, false);
      this.selectedNodeIds.delete(numericId);
      if (this.primarySelectedId === numericId) {
        this.primarySelectedId = null;
      }
    } else {
      this._updateNodeSelectionClass(resolvedId, g, true);
      this.selectedNodeIds.add(numericId);
      this.primarySelectedId = numericId;
    }

    this.selectedNodeIds = new Set(this._getSelectedIdsFromDom());
    this._refreshPrimarySelection(g);
    widget.emitEventSelectedSignal(this.getSelection());
    widget.emitSelectedNodeIdsSignal(this.getSelectedIds());
  }

  selectForContextMenu(id, g) {
    const resolvedId = this._resolveNodeId(g, id);
    const element = this.getElement(resolvedId);
    const numericId = parseInt(resolvedId, 10);
    const isSelected = !!element && (element.classed('selected') || this.selectedNodeIds.has(numericId));
    if (!isSelected) {
      this.select(id, g);
      return;
    }
    this.selectedNodeIds = new Set(this.getSelectedIds());
    this.selectedNodeIds.add(numericId);
    this.primarySelectedId = numericId;
    this._updateEdgeHighlights(g);
    widget.emitEventSelectedSignal(numericId);
    widget.emitSelectedNodeIdsSignal(this.getSelectedIds());
  }

  selectMany(ids, g) {
    this.clearSelectionWithoutEmittingSignal();
    for (const id of ids) {
      this._updateNodeSelectionClass(id, g, true);
      this.selectedNodeIds.add(parseInt(id, 10));
    }
    this.primarySelectedId = ids.length ? parseInt(ids[0], 10) : null;
    this._refreshPrimarySelection(g);
    widget.emitEventSelectedSignal(this.getSelection());
    widget.emitSelectedNodeIdsSignal(this.getSelectedIds());
  }

  getElement(id) {
    const element = d3.select(`#n${id}`);
    return element.empty() ? null : element;
  }

  getViewport() {
    return {
      translate: this.zoom.translate().slice(),
      scale: this.zoom.scale(),
    };
  }

  restoreViewport(viewport) {
    if (!viewport) {
      return;
    }
    this.zoom.scale(viewport.scale);
    this.zoom.translate(viewport.translate.slice());
    this.updateTransform();
  }

  viewportCenterPoint() {
    const svgNode = this.svg.node();
    if (!svgNode) {
      return { x: window.innerWidth / 2, y: window.innerHeight / 2 };
    }
    const rect = svgNode.getBoundingClientRect();
    return {
      x: rect.left + (rect.width / 2),
      y: rect.top + (rect.height / 2),
    };
  }

  closestNodeIdToViewportCenter() {
    const viewportCenter = this.viewportCenterPoint();
    let closestId = null;
    let closestDistance = Number.POSITIVE_INFINITY;
    this.svgGroup.selectAll('.node').each(function(id) {
      const rect = this.getBoundingClientRect();
      if (!rect || rect.width <= 0 || rect.height <= 0) {
        return;
      }
      const dx = (rect.left + (rect.width / 2)) - viewportCenter.x;
      const dy = (rect.top + (rect.height / 2)) - viewportCenter.y;
      const distance = (dx * dx) + (dy * dy);
      if (distance < closestDistance) {
        closestDistance = distance;
        closestId = id;
      }
    });
    return closestId == null ? null : parseInt(closestId, 10);
  }

  isElementVisible(id, margin=40) {
    const element = this.getElement(id);
    if (!element) {
      return false;
    }
    const rect = element.node().getBoundingClientRect();
    return rect.right >= margin
      && rect.bottom >= margin
      && rect.left <= (window.innerWidth - margin)
      && rect.top <= (window.innerHeight - margin);
  }

  scrollTo(id, center=false, duration=1000, targetScale=null) {
    const element = this.getElement(id);
    if (!element) {
      return false;
    }
    const scale = targetScale == null ? this.zoom.scale() : targetScale;
    this.svg.interrupt();
    if (targetScale != null) {
      this.zoom.scale(scale);
    }

    const svgNode = this.svg.node();
    const elementNode = element.node();
    if (!svgNode || !elementNode) {
      return false;
    }

    const nodeTransform = d3.transform(element.attr('transform'));
    const [nodeX, nodeY] = nodeTransform.translate;
    const bbox = elementNode.getBBox();
    const graphCenterX = nodeX + bbox.x + (bbox.width / 2);
    const graphCenterY = nodeY + bbox.y + (bbox.height / 2);
    const targetX = svgNode.clientWidth / 2;
    const targetY = center ? (svgNode.clientHeight / 2) : 60;
    const nextTranslate = [
      targetX - (graphCenterX * scale),
      targetY - (graphCenterY * scale),
    ];

    this.svg.transition().duration(duration)
      .call(this.zoom.translate(nextTranslate).event);
    return true;
  }

  fitToContent(padding=GRAPH_FIT_PADDING) {
    const svgNode = this.svg.node();
    const groupNode = this.svgGroup.node();
    if (!svgNode || !groupNode) {
      return false;
    }

    let bbox;
    try {
      bbox = groupNode.getBBox();
    } catch (error) {
      return false;
    }

    const svgWidth = svgNode.clientWidth || window.innerWidth;
    const svgHeight = svgNode.clientHeight || window.innerHeight;
    if (!bbox || bbox.width <= 0 || bbox.height <= 0 || svgWidth <= 0 || svgHeight <= 0) {
      this.zoom.scale(1);
      this.zoom.translate([padding / 2, padding / 2]);
      this.updateTransform();
      return false;
    }

    const availableWidth = Math.max(1, svgWidth - (padding * 2));
    const availableHeight = Math.max(1, svgHeight - (padding * 2));
    const scale = Math.min(
      GRAPH_FIT_MAX_SCALE,
      availableWidth / bbox.width,
      availableHeight / bbox.height
    );
    const graphCenterX = bbox.x + (bbox.width / 2);
    const graphCenterY = bbox.y + (bbox.height / 2);
    const nextTranslate = [
      (svgWidth / 2) - (graphCenterX * scale),
      (svgHeight / 2) - (graphCenterY * scale),
    ];

    this.svg.interrupt();
    this.zoom.scale(scale);
    this.zoom.translate(nextTranslate);
    this.updateTransform();
    return true;
  }

  render(g, transitionMs=GRAPH_TRANSITION_MS) {
    const visibleGraph = new graphlib.Graph({ multigraph: true });
    visibleGraph.setGraph({});
    visibleGraph.graph().transition = (selection) => {
      if (!transitionMs) {
        return selection;
      }
      return selection.transition().duration(transitionMs);
    };

    for (const v of g.nodes()) {
      if (!this.nodeWhitelist || this.nodeWhitelist.has(v)) {
        visibleGraph.setNode(v, g.node(v));
      }
    }
    for (const e of g.edges()) {
      if (!this.nodeWhitelist || this.nodeWhitelist.has(e.v)) {
        visibleGraph.setEdge(e, g.edge(e));
      }
    }

    const dagreRenderer = dagreD3.render();
    this.svgGroup.selectAll('*').interrupt();
    this.svgGroup.selectAll('*').remove();
    this.svgGroup.call(dagreRenderer, visibleGraph);
    this._restoreRawNodeLabels(visibleGraph);
    this._styleMessageTags();
    this._fitNodeBoxesToLabels();
    this.svgGroup.selectAll('.node')
      .on('click', (id) => {
        if (isMultiSelectEvent(d3.event)) {
          this.toggleSelection(id, g);
        } else {
          this.select(id, g);
        }
        d3.event.stopPropagation();
      })
      .on('dblclick', (id) => {
        if (actionsProhibited) {
          d3.event.stopPropagation();
          return;
        }

        const node = g.node(id);
        const classes = node.class.split(' ');
        if (classes.includes('entry')) {
          widget.renameEntryPoint(parseInt(id, 10));
        } else if (classes.includes('fork')) {
          widget.editForkBranches(parseInt(id, 10));
        } else {
          widget.editEvent(parseInt(id, 10));
        }
        d3.event.stopPropagation();
      })
      .on('contextmenu', (id) => {
        this.selectForContextMenu(id, g);
        d3.contextMenu(handleNodeContextMenu).call(this, id);
        clampContextMenuToViewport();
        d3.event.stopPropagation();
      });
    for (const id of this.getSelectedIds()) {
      this._updateNodeSelectionClass(id, g, true);
    }
    this._refreshPrimarySelection(g);
  }

  setScale(scale) { this.zoom.scale(scale); this.updateTransform(); }
  setTranslate(translate) { this.zoom.translate(translate); this.updateTransform(); }

  updateTransform() {
    this.svgGroup.attr('transform', `translate(${this.zoom.translate()})scale(${this.zoom.scale()})`);
  }
}

class Graph {
  constructor() {
    this.g = null;
    this.data = null;
    this.renderer = new Renderer();
    this.persistentComponentRootName = null;
  }

  update(data) {
    this.data = data;
    this.g = new graphlib.Graph({ multigraph: true });
    this.g.setGraph({});

    for (const entry of data) {
      if (entry.type === 'node') {
        const rawLabel = getNodeLabel(entry);
        this.g.setNode(entry.id, {
          label: getNodeLayoutLabel(rawLabel),
          rawLabel,
          'class': entry.node_type,
          id: `n${entry.id}`,
          idx: entry.id,
          name: entry.data.name,
        });
      } else if (entry.type === 'edge') {
        this.g.setEdge(entry.source, entry.target, {
          labelType: 'html',
          label: `<span id="label-edge-${entry.source}-${entry.target}-${entry.data.value}">${entry.data.value == null ? '' : entry.data.value}</span>`,
          'class': `edge-${entry.source}-${entry.target}`,
          virtual: !!entry.data.virtual,
        }, `edge-${entry.source}-${entry.target}-${entry.data.value}`);
      }
    }
  }

  refresh() {
    if (this.data && Object.keys(this.data).length > 0) {
      this.update(this.data);
    }
  }

  render(transitionMs=GRAPH_TRANSITION_MS) {
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

    this.renderer.render(this.g, transitionMs);
    refreshGraphSearch(false);
  }

  hasPersistentComponentFilter() {
    return !!this.persistentComponentRootName;
  }

  clearPersistentComponentFilter() {
    this.persistentComponentRootName = null;
  }

  _findNodeIdByName(name) {
    if (!this.g || name == null) {
      return null;
    }
    for (const nodeId of this.g.nodes()) {
      const node = this.g.node(nodeId);
      if (node && node.name === name) {
        return nodeId;
      }
    }
    return null;
  }

  findNodeComponentIds(v) {
    if (!this.g || v == null) {
      return null;
    }
    const resolvedId = `${v}`;
    const components = graphlib.alg.components(this.g);
    const component = components.find((entry) => entry.includes(resolvedId));
    return component ? new Set(component) : null;
  }

  findPersistentComponentIds() {
    const rootId = this._findNodeIdByName(this.persistentComponentRootName);
    if (rootId == null) {
      return null;
    }
    return this.findNodeComponentIds(rootId);
  }

  renderOnlyConnected(v) {
    const selected = this.renderer.getSelection();
    if (v == null) {
      this.clearPersistentComponentFilter();
    } else {
      const node = this.g ? this.g.node(`${v}`) : null;
      this.persistentComponentRootName = node ? node.name : null;
    }
    this.render();
    if (v != null && this.renderer.getElement(v)) {
      setTimeout(() => this.renderer.scrollTo(v, true, 500, READABLE_NODE_SCALE), 500);
    } else if (selected !== -1 && this.renderer.getElement(selected)) {
      setTimeout(() => this.renderer.scrollTo(selected, true, 500, READABLE_NODE_SCALE), 500);
    }
  }

  selectConnected(v) {
    const component = this.findNodeComponentIds(v);
    if (!component) {
      return;
    }
    const ids = [...component]
      .map((nodeId) => parseInt(nodeId, 10))
      .filter((nodeId) => !Number.isNaN(nodeId) && nodeId >= 0);
    this.renderer.selectMany(ids, this.g);
  }

}

graph = new Graph();

function pushNodeParams(parts, node) {
  if (!node || !node.data || !node.data.params) {
    return;
  }
  try {
    parts.push(JSON.stringify(node.data.params));
  } catch (err) {
    // Ignore non-serializable values.
  }
}

function pushNodeIdentity(parts, node) {
  if (!node || !node.data) {
    return;
  }
  if (node.data.name) {
    parts.push(node.data.name);
  }
  if (node.data.actor) {
    parts.push(node.data.actor);
  }
  if (node.data.action) {
    parts.push(node.data.action);
  }
  if (node.data.query) {
    parts.push(node.data.query);
  }
}

function pushMalsText(parts, node) {
  if (!node || !node.data) {
    return;
  }
  if (node.data._message_text) {
    parts.push(node.data._message_text);
  }
  if (node.data._choice_label_texts) {
    for (const value of Object.values(node.data._choice_label_texts)) {
      parts.push(value);
    }
  }
}

function getSearchableNodeText(node, scope='all') {
  if (!node || !node.data) {
    return '';
  }

  const parts = [];
  if (scope === 'mals') {
    pushMalsText(parts, node);
    return parts.join('\n');
  }
  if (scope === 'params') {
    pushNodeParams(parts, node);
    return parts.join('\n');
  }
  if (scope === 'events') {
    pushNodeIdentity(parts, node);
    return parts.join('\n');
  }
  if (scope === 'switches') {
    if (node.node_type !== 'switch') {
      return '';
    }
    pushNodeIdentity(parts, node);
    pushNodeParams(parts, node);
    return parts.join('\n');
  }
  if (scope === 'subflows') {
    if (node.node_type !== 'sub_flow') {
      return '';
    }
    pushNodeIdentity(parts, node);
    if (node.data.entry_point_name) {
      parts.push(node.data.entry_point_name);
    }
    if (node.data.res_flowchart_name) {
      parts.push(node.data.res_flowchart_name);
    }
    pushNodeParams(parts, node);
    return parts.join('\n');
  }

  pushNodeIdentity(parts, node);
  pushNodeParams(parts, node);
  pushMalsText(parts, node);
  if (node.data.entry_point_name) {
    parts.push(node.data.entry_point_name);
  }
  if (node.data.res_flowchart_name) {
    parts.push(node.data.res_flowchart_name);
  }
  return parts.join('\n');
}

function clearSearchHighlightClasses() {
  d3.selectAll('.node.search-match').classed('search-match', false);
  d3.selectAll('.node.search-current').classed('search-current', false);
}

function applySearchHighlights() {
  clearSearchHighlightClasses();
  if (!graphSearchMatches.length || !graph || !graph.renderer) {
    return;
  }

  for (const nodeId of graphSearchMatches) {
    const element = graph.renderer.getElement(nodeId);
    if (element) {
      element.classed('search-match', true);
    }
  }

  if (graphSearchIndex >= 0 && graphSearchIndex < graphSearchMatches.length) {
    const currentElement = graph.renderer.getElement(graphSearchMatches[graphSearchIndex]);
    if (currentElement) {
      currentElement.classed('search-current', true);
    }
  }
}

function emitSearchResults() {
  if (!widget || !widget.emitSearchResultsSignal) {
    return;
  }
  widget.emitSearchResultsSignal(graphSearchMatches.length, graphSearchIndex);
}

function scrollToCurrentSearchResult(duration=500) {
  if (graphSearchIndex < 0 || graphSearchIndex >= graphSearchMatches.length) {
    return;
  }
  const targetId = graphSearchMatches[graphSearchIndex];
  if (graph && graph.g && graph.g.node(targetId)) {
    graph.renderer.select(targetId, graph.g, false);
  }
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
      if (!haystack) {
        return false;
      }
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
  if (scrollToResult) {
    scrollToCurrentSearchResult();
  }
}

window.eventEditorSetSearchQuery = function(query, caseInsensitive, scrollToResult, scope='all') {
  graphSearchQuery = (query || '').trim();
  graphSearchCaseInsensitive = !!caseInsensitive;
  graphSearchScope = ['all', 'mals', 'params', 'events', 'switches', 'subflows'].includes(scope) ? scope : 'all';
  refreshGraphSearch(!!scrollToResult);
};

window.eventEditorSetRenderMessageTagsAsStyling = function(enabled) {
  renderMessageTagsAsStyling = !!enabled;
};

window.eventEditorSetShowNonTextMessageTags = function(visible) {
  showNonTextMessageTags = !!visible;
};

window.eventEditorSetIncludeMessageBlankLines = function(include) {
  includeMessageBlankLines = !!include;
};

window.eventEditorSetShowMessageBubbleBreaks = function(show) {
  showMessageBubbleBreaks = !!show;
};

window.eventEditorStepSearch = function(delta) {
  if (!graphSearchMatches.length) {
    emitSearchResults();
    return;
  }
  const offset = delta < 0 ? -1 : 1;
  graphSearchIndex = (graphSearchIndex + offset + graphSearchMatches.length) % graphSearchMatches.length;
  applySearchHighlights();
  emitSearchResults();
  scrollToCurrentSearchResult(350);
};

window.eventEditorSetSearchIndex = function(index) {
  if (!graphSearchMatches.length) {
    emitSearchResults();
    return;
  }
  const clampedIndex = Math.max(0, Math.min(graphSearchMatches.length - 1, parseInt(index, 10) || 0));
  graphSearchIndex = clampedIndex;
  applySearchHighlights();
  emitSearchResults();
  scrollToCurrentSearchResult(350);
};

document.body.addEventListener('keydown', (event) => {
  const key = event.key; // "ArrowRight", "ArrowLeft", "ArrowUp", or "ArrowDown"

  if (key === 'Escape') {
    graph.renderer.clearSelection();
    return;
  }

  // Handle zoom
  if (event.ctrlKey) {
    let scaleMultiplier = 1;
    if (key === 'ArrowUp')
      scaleMultiplier = 1.1;
    else if (key === 'ArrowDown')
      scaleMultiplier = 0.9;
    graph.renderer.setScale(graph.renderer.zoom.scale() * scaleMultiplier);
    if (scaleMultiplier !== 1)
      return;
  }

  // Handle translate / navigation
  const selected = graph.renderer.getSelection();
  if (selected === -1) {
    let vDirection = 0;
    let hDirection = 0;
    switch (key) {
      case 'ArrowUp':
        vDirection = 1;
        break;
      case 'ArrowDown':
        vDirection = -1;
        break;
      case 'ArrowLeft':
        hDirection = 1;
        break;
      case 'ArrowRight':
        hDirection = -1;
        break;
    }
    const [x, y] = graph.renderer.zoom.translate();
    graph.renderer.setTranslate([x + 100 * hDirection, y + 100 * vDirection]);
    return;
  }
  if (key === 'ArrowUp' || key === 'ArrowDown') {
    const nodes = key === 'ArrowUp' ? graph.g.predecessors(selected) : graph.g.successors(selected);
    if (nodes.length > 0) {
      graph.renderer.scrollTo(nodes[0], true, 500);
      graph.renderer.select(nodes[0], graph.g);
    }
  }
});

new QWebChannel(qt.webChannelTransport, (channel) => {
  widget = channel.objects.widget;

  function select(id) {
    if (graph.hasPersistentComponentFilter()) {
      graph.renderOnlyConnected(id);
      graph.renderer.select(id, graph.g);
    } else {
      graph.renderer.select(id, graph.g);
      graph.renderer.scrollTo(id, true, 500, READABLE_NODE_SCALE);
    }
  }

  function reveal(id) {
    if (graph.hasPersistentComponentFilter() && !graph.renderer.getElement(id)) {
      graph.clearPersistentComponentFilter();
      graph.render();
    }
    graph.renderer.select(id, graph.g);
    graph.renderer.scrollTo(id, true, 500, READABLE_NODE_SCALE);
  }

  function load(cb) {
    const loadToken = ++pendingLoadFinalizeToken;
    widget.getJson((data) => {
      if (!data) {
        return;
      }
      const transitionMs = nextGraphTransitionMs;
      nextGraphTransitionMs = GRAPH_TRANSITION_MS;
      graph.update(data);
      graph.render(transitionMs);
      const finalizeLoad = () => {
        if (loadToken !== pendingLoadFinalizeToken) {
          return;
        }
        if (preservedViewport && !resetViewportOnNextLoad) {
          graph.renderer.restoreViewport(preservedViewport);
          if (preservedFocusNodeId != null) {
            const focusedElement = graph.renderer.getElement(preservedFocusNodeId);
            const currentCenter = getElementCenterInViewport(focusedElement);
            if (currentCenter && preservedFocusPoint) {
              const nextTranslate = graph.renderer.zoom.translate().slice();
              nextTranslate[0] += preservedFocusPoint.x - currentCenter.x;
              nextTranslate[1] += preservedFocusPoint.y - currentCenter.y;
              graph.renderer.zoom.translate(nextTranslate);
              graph.renderer.updateTransform();
            }
          }
        }
        if (resetViewportOnNextLoad) {
          graph.renderer.fitToContent();
          resetViewportOnNextLoad = false;
        }
        widget.emitReloadedSignal();
        if (cb) {
          cb(data);
        }
        isDeleting = false;
        suppressNextViewportAdjustment = false;
        preservedViewport = null;
        preservedFocusNodeId = null;
        preservedFocusPoint = null;
      };

      setTimeout(finalizeLoad, transitionMs + 20);
    });
  }

  widget.flowDataChanged.connect(() => {
    load();
  });

  widget.fileLoaded.connect(() => {
    graph.clearPersistentComponentFilter();
    graph.renderer.clearSelection();
    preservedViewport = null;
    resetViewportOnNextLoad = true;
  });

  widget.selectRequested.connect((id) => {
    select(id);
  });

  widget.revealRequested.connect((id) => {
    reveal(id);
  });

  widget.instantRevealRequested.connect((id) => {
    if (graph.hasPersistentComponentFilter() && !graph.renderer.getElement(id)) {
      graph.clearPersistentComponentFilter();
      graph.render(0);
    }
    graph.renderer.select(id, graph.g);
    graph.renderer.scrollTo(id, true, 0, READABLE_NODE_SCALE);
  });

  widget.preserveViewportRequested.connect(() => {
    preservedViewport = graph.renderer.getViewport();
    preservedFocusNodeId = graph.renderer.closestNodeIdToViewportCenter();
    preservedFocusPoint = preservedFocusNodeId == null ? null : graph.renderer.viewportCenterPoint();
    suppressNextViewportAdjustment = true;
  });

  widget.fastGraphReloadRequested.connect(() => {
    nextGraphTransitionMs = 0;
  });

  widget.eventNameVisibilityChanged.connect((visible) => {
    eventNamesVisible = visible;
  });

  widget.eventParamVisibilityChanged.connect((visible) => {
    eventParamVisible = visible;
  });

  widget.eventMessageVisibilityChanged.connect((visible) => {
    eventMessagesVisible = visible;
  });

  widget.actionProhibitionChanged.connect((value) => {
    actionsProhibited = value;
  });

  widget.entryPointFilterStateChanged.connect((value) => {
    hasHiddenEntryPoints = !!value;
  });

  widget.emitReadySignal();
  load();
});
