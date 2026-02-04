<template>
	<Teleport to="body">
		<div
			v-if="visible"
			class="context-menu-overlay"
			@click="close"
			@contextmenu.prevent="close"
		>
			<div
				class="context-menu"
				:style="menuStyle"
				@click.stop
				@keydown="onKeydown"
				ref="menuRef"
				tabindex="0"
			>
				<!-- Multi-selection header -->
				<div v-if="selectedCount > 1" class="context-menu-header">
					{{ selectedCount }} {{ __("emails selected") }}
				</div>

				<template v-for="(item, index) in filteredItems" :key="item.id || index">
					<div v-if="item.separator" class="menu-separator"></div>
					<div
						v-else
						class="menu-item"
						:class="{
							disabled: item.disabled,
							danger: item.danger,
							active: focusedIndex === index,
							'has-submenu': item.submenu && item.submenu.length > 0,
						}"
						@click="!item.disabled && selectItem(item)"
						@mouseenter="onItemHover(item, index)"
						@mouseleave="onItemLeave(item)"
					>
						<component :is="item.icon" v-if="item.icon" :size="16" class="menu-icon" />
						<span class="menu-label">{{ item.label }}</span>
						<ChevronRight
							v-if="item.submenu && item.submenu.length > 0"
							:size="14"
							class="submenu-arrow"
						/>
					</div>

					<!-- Submenu -->
					<div
						v-if="item.submenu && item.submenu.length > 0 && activeSubmenu === item.id"
						class="submenu"
						:style="submenuStyle"
					>
						<div
							v-for="sub in item.submenu"
							:key="sub.id"
							class="menu-item"
							:class="{ disabled: sub.disabled }"
							@click="!sub.disabled && selectSubmenuItem(item, sub)"
						>
							<component
								:is="sub.icon"
								v-if="sub.icon"
								:size="16"
								class="menu-icon"
							/>
							<span class="menu-label">{{ sub.label }}</span>
						</div>
					</div>
				</template>
			</div>
		</div>
	</Teleport>
</template>

<script>
import { ChevronRight } from "lucide-vue-next";

export default {
	name: "ContextMenu",

	components: {
		ChevronRight,
	},

	props: {
		items: {
			type: Array,
			default: () => [],
			// Each item: { id, label, icon, action, disabled, separator, danger, submenu }
		},
		position: {
			type: Object,
			default: () => ({ x: 0, y: 0 }),
		},
		visible: {
			type: Boolean,
			default: false,
		},
		selectedCount: {
			type: Number,
			default: 1,
		},
	},

	emits: ["select", "close"],

	data() {
		return {
			activeSubmenu: null,
			submenuTimeout: null,
			focusedIndex: -1,
			menuPosition: { x: 0, y: 0 },
		};
	},

	computed: {
		menuStyle() {
			return {
				left: `${this.menuPosition.x}px`,
				top: `${this.menuPosition.y}px`,
			};
		},

		submenuStyle() {
			// Position submenu to the right of the parent menu
			return {
				left: "100%",
				top: "0",
			};
		},

		filteredItems() {
			// When multiple items selected, remove reply/forward options
			if (this.selectedCount > 1) {
				const excludeActions = ["reply", "reply-all", "forward"];
				return this.items.filter((item) => {
					if (item.separator) return true;
					return !excludeActions.includes(item.action || item.id);
				});
			}
			return this.items;
		},

		selectableItems() {
			return this.filteredItems.filter((item) => !item.separator && !item.disabled);
		},
	},

	watch: {
		visible(val) {
			if (val) {
				this.activeSubmenu = null;
				this.focusedIndex = -1;
				this.calculatePosition();
				this.$nextTick(() => {
					if (this.$refs.menuRef) {
						this.$refs.menuRef.focus();
					}
				});
			}
		},
		position: {
			handler() {
				if (this.visible) {
					this.calculatePosition();
				}
			},
			deep: true,
		},
	},

	mounted() {
		document.addEventListener("keydown", this.onGlobalKeydown);
	},

	beforeUnmount() {
		document.removeEventListener("keydown", this.onGlobalKeydown);
		if (this.submenuTimeout) {
			clearTimeout(this.submenuTimeout);
		}
	},

	methods: {
		calculatePosition() {
			// Get viewport dimensions
			const viewportWidth = window.innerWidth;
			const viewportHeight = window.innerHeight;

			// Estimated menu dimensions
			const menuWidth = 200;
			const menuHeight =
				this.filteredItems.length * 36 + 20 + (this.selectedCount > 1 ? 40 : 0);

			let x = this.position.x;
			let y = this.position.y;

			// Adjust horizontal position if menu would overflow right
			if (x + menuWidth > viewportWidth - 10) {
				x = viewportWidth - menuWidth - 10;
			}

			// Adjust vertical position if menu would overflow bottom
			if (y + menuHeight > viewportHeight - 10) {
				y = viewportHeight - menuHeight - 10;
			}

			// Ensure minimum positions
			x = Math.max(10, x);
			y = Math.max(10, y);

			this.menuPosition = { x, y };
		},

		close() {
			this.activeSubmenu = null;
			this.$emit("close");
		},

		selectItem(item) {
			if (item.disabled) return;

			// If item has submenu, toggle it
			if (item.submenu && item.submenu.length > 0) {
				this.activeSubmenu = this.activeSubmenu === item.id ? null : item.id;
				return;
			}

			// Emit selection and close
			this.$emit("select", { item, action: item.action || item.id });
			this.close();
		},

		selectSubmenuItem(parentItem, subItem) {
			if (subItem.disabled) return;

			this.$emit("select", {
				item: subItem,
				parentItem,
				action: subItem.action || subItem.id,
			});
			this.close();
		},

		onItemHover(item, index) {
			this.focusedIndex = index;

			if (this.submenuTimeout) {
				clearTimeout(this.submenuTimeout);
			}

			if (item.submenu && item.submenu.length > 0) {
				// Delay opening submenu
				this.submenuTimeout = setTimeout(() => {
					this.activeSubmenu = item.id;
				}, 150);
			} else {
				// Close any open submenu after delay
				this.submenuTimeout = setTimeout(() => {
					this.activeSubmenu = null;
				}, 150);
			}
		},

		onItemLeave(item) {
			// Keep submenu open when moving to it
		},

		onKeydown(event) {
			this.handleKeyNavigation(event);
		},

		onGlobalKeydown(event) {
			if (!this.visible) return;

			if (event.key === "Escape") {
				event.preventDefault();
				this.close();
			}
		},

		handleKeyNavigation(event) {
			const itemsCount = this.filteredItems.length;

			switch (event.key) {
				case "ArrowDown":
					event.preventDefault();
					this.focusedIndex = this.findNextSelectableIndex(this.focusedIndex, 1);
					break;

				case "ArrowUp":
					event.preventDefault();
					this.focusedIndex = this.findNextSelectableIndex(this.focusedIndex, -1);
					break;

				case "ArrowRight":
					event.preventDefault();
					if (this.focusedIndex >= 0) {
						const item = this.filteredItems[this.focusedIndex];
						if (item.submenu && item.submenu.length > 0) {
							this.activeSubmenu = item.id;
						}
					}
					break;

				case "ArrowLeft":
					event.preventDefault();
					this.activeSubmenu = null;
					break;

				case "Enter":
				case " ":
					event.preventDefault();
					if (this.focusedIndex >= 0) {
						const item = this.filteredItems[this.focusedIndex];
						if (!item.disabled && !item.separator) {
							this.selectItem(item);
						}
					}
					break;

				case "Escape":
					event.preventDefault();
					this.close();
					break;
			}
		},

		findNextSelectableIndex(currentIndex, direction) {
			const itemsCount = this.filteredItems.length;
			let nextIndex = currentIndex;

			for (let i = 0; i < itemsCount; i++) {
				nextIndex = (nextIndex + direction + itemsCount) % itemsCount;
				const item = this.filteredItems[nextIndex];
				if (!item.separator && !item.disabled) {
					return nextIndex;
				}
			}

			return currentIndex;
		},
	},
};
</script>

<style scoped>
.context-menu-overlay {
	position: fixed;
	top: 0;
	left: 0;
	right: 0;
	bottom: 0;
	z-index: 9999;
}

.context-menu {
	position: fixed;
	min-width: 180px;
	max-width: 280px;
	background: var(--card-bg, white);
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 8px;
	box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
	padding: 6px 0;
	outline: none;
	z-index: 10000;
}

.context-menu-header {
	padding: 8px 14px;
	font-size: 12px;
	font-weight: 600;
	color: var(--primary-color, #2490ef);
	background: var(--subtle-accent, rgba(36, 144, 239, 0.08));
	border-bottom: 1px solid var(--border-color, #e5e5e5);
	margin-bottom: 4px;
}

.menu-item {
	display: flex;
	align-items: center;
	gap: 10px;
	padding: 8px 14px;
	cursor: pointer;
	font-size: 13px;
	color: var(--text-color, #333);
	transition: background 0.1s ease;
	position: relative;
}

.menu-item:hover,
.menu-item.active {
	background: var(--bg-light-gray, #f5f5f5);
}

.menu-item.disabled {
	opacity: 0.5;
	cursor: not-allowed;
}

.menu-item.disabled:hover {
	background: transparent;
}

.menu-item.danger {
	color: var(--red-500, #ef4444);
}

.menu-item.danger:hover {
	background: rgba(239, 68, 68, 0.1);
}

.menu-icon {
	flex-shrink: 0;
	color: var(--text-muted, #8d99a6);
}

.menu-item.danger .menu-icon {
	color: var(--red-500, #ef4444);
}

.menu-label {
	flex: 1;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.submenu-arrow {
	flex-shrink: 0;
	color: var(--text-muted, #8d99a6);
	margin-left: auto;
}

.menu-separator {
	height: 1px;
	background: var(--border-color, #e5e5e5);
	margin: 6px 0;
}

.submenu {
	position: absolute;
	left: 100%;
	top: 0;
	min-width: 160px;
	max-width: 250px;
	max-height: 300px;
	overflow-y: auto;
	background: var(--card-bg, white);
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 8px;
	box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
	padding: 6px 0;
	margin-left: 4px;
	z-index: 10001;
}

.has-submenu {
	padding-right: 30px;
}
</style>
