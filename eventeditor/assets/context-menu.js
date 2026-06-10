// Minimal vanilla context menu, replacing d3-context-menu.
//
// Usage:
//   showContextMenu(actions, clientX, clientY)
//
// `actions` is an array of either:
//   { title: 'Label', action: () => { ... } }
//   { divider: true }
//
// Only one menu can be open at a time; opening a new one closes the
// previous one. The menu closes itself on click-away, Escape, scroll,
// or after an item is activated.

(function () {
  let activeMenu = null;
  let activeCleanup = null;

  function closeContextMenu() {
    if (activeMenu) {
      activeMenu.remove();
      activeMenu = null;
    }
    if (activeCleanup) {
      activeCleanup();
      activeCleanup = null;
    }
  }

  function clampToViewport(menuEl, x, y) {
    // Start at the requested point, then measure and clamp.
    menuEl.style.left = `${x}px`;
    menuEl.style.top = `${y}px`;

    const rect = menuEl.getBoundingClientRect();
    const maxLeft = Math.max(8, window.innerWidth - rect.width - 8);
    const maxTop = Math.max(8, window.innerHeight - rect.height - 8);
    const left = Math.max(8, Math.min(x, maxLeft));
    const top = Math.max(8, Math.min(y, maxTop));
    menuEl.style.left = `${left}px`;
    menuEl.style.top = `${top}px`;
  }

  function showContextMenu(actions, x, y) {
    closeContextMenu();
    if (!actions || !actions.length) {
      return;
    }

    const menu = document.createElement('div');
    menu.className = 'context-menu';

    // Drop a leading/trailing divider and collapse repeats so we don't
    // render stray <hr> elements.
    let lastWasDivider = true; // suppress a leading divider
    for (const item of actions) {
      if (item.divider) {
        if (lastWasDivider) {
          continue;
        }
        const hr = document.createElement('hr');
        hr.className = 'context-menu-divider';
        menu.appendChild(hr);
        lastWasDivider = true;
        continue;
      }

      const entry = document.createElement('div');
      entry.className = 'context-menu-item';
      entry.textContent = item.title;
      entry.addEventListener('click', (event) => {
        event.stopPropagation();
        closeContextMenu();
        if (item.action) {
          item.action();
        }
      });
      menu.appendChild(entry);
      lastWasDivider = false;
    }

    // Drop a trailing divider, if any.
    while (menu.lastChild && menu.lastChild.classList && menu.lastChild.classList.contains('context-menu-divider')) {
      menu.removeChild(menu.lastChild);
    }

    document.body.appendChild(menu);
    activeMenu = menu;
    clampToViewport(menu, x, y);

    const onPointerDown = (event) => {
      if (!menu.contains(event.target)) {
        closeContextMenu();
      }
    };
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        closeContextMenu();
      }
    };
    const onScroll = () => closeContextMenu();
    const onContextMenu = (event) => {
      if (!menu.contains(event.target)) {
        closeContextMenu();
      }
    };

    // Use capture so this fires before other handlers, and a tiny delay
    // so the click that opened the menu doesn't immediately close it.
    setTimeout(() => {
      document.addEventListener('mousedown', onPointerDown, true);
      document.addEventListener('contextmenu', onContextMenu, true);
      document.addEventListener('keydown', onKeyDown, true);
      window.addEventListener('scroll', onScroll, true);
      window.addEventListener('resize', onScroll, true);
    }, 0);

    activeCleanup = () => {
      document.removeEventListener('mousedown', onPointerDown, true);
      document.removeEventListener('contextmenu', onContextMenu, true);
      document.removeEventListener('keydown', onKeyDown, true);
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onScroll, true);
    };
  }

  window.showContextMenu = showContextMenu;
  window.closeContextMenu = closeContextMenu;
})();
