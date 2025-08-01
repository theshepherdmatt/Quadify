from PIL import ImageFont


def compute_visible_window(items, current_selection_index, window_start_index, window_size):
    """Compute the visible slice of items for scrolling menus."""
    if current_selection_index < window_start_index:
        window_start_index = current_selection_index
    elif current_selection_index >= window_start_index + window_size:
        window_start_index = current_selection_index - window_size + 1

    window_start_index = max(0, window_start_index)
    window_start_index = min(window_start_index, max(0, len(items) - window_size))
    visible_items = items[window_start_index: window_start_index + window_size]
    return visible_items, window_start_index


def render_list_menu(display_manager, title, items, current_selection_index, window_start_index, window_size=4, y_offset=0, line_spacing=16, font_key="menu_font"):
    """Render a simple text menu with a highlighted selection."""
    font = display_manager.fonts.get(font_key, ImageFont.load_default())
    visible_items, window_start_index = compute_visible_window(items, current_selection_index, window_start_index, window_size)

    def draw(draw_obj):
        y = y_offset
        draw_obj.text((0, y), title[:20], font=font, fill="yellow")
        y += line_spacing
        for i, item in enumerate(visible_items):
            actual_index = window_start_index + i
            prefix = "-> " if actual_index == current_selection_index else "   "
            fill = "white" if actual_index == current_selection_index else "gray"
            item_title = item.get("title", "Untitled")
            draw_obj.text((0, y + i * line_spacing), f"{prefix}{item_title[:20]}", font=font, fill=fill)
    display_manager.draw_custom(draw)
    return window_start_index
