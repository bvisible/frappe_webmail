<template>
	<div v-if="show" class="attachment-picker-overlay" @click.self="$emit('close')">
		<div class="attachment-picker-modal">
			<!-- Header -->
			<div class="picker-header">
				<h3>{{ __("Attach from...") }}</h3>
				<button @click="$emit('close')" class="btn-close">
					<X :size="20" />
				</button>
			</div>

			<!-- Tabs -->
			<div class="picker-tabs">
				<button
					v-for="tab in availableTabs"
					:key="tab.id"
					:class="{ active: activeTab === tab.id }"
					@click="activeTab = tab.id"
				>
					<component :is="tab.icon" :size="16" />
					<span>{{ tab.label }}</span>
				</button>
			</div>

			<!-- Content -->
			<div class="picker-content">
				<!-- Local Upload Tab -->
				<div v-if="activeTab === 'local'" class="tab-content local-tab">
					<div
						class="drop-zone"
						:class="{ dragging: isDragging }"
						@dragover.prevent="isDragging = true"
						@dragleave.prevent="isDragging = false"
						@drop.prevent="handleDrop"
						@click="triggerFileInput"
					>
						<input
							type="file"
							ref="localFileInput"
							multiple
							@change="handleLocalFileSelect"
							style="display: none"
						/>
						<Upload :size="48" class="drop-icon" />
						<p class="drop-text">{{ __("Drop files here or click to browse") }}</p>
						<p class="drop-hint">{{ __("Maximum 25 MB per file") }}</p>
					</div>

					<!-- Selected files list -->
					<div v-if="localFiles.length > 0" class="local-files-list">
						<div class="local-files-header">
							<span>{{ __("Selected files") }} ({{ localFiles.length }})</span>
							<button class="btn-clear-all" @click="clearLocalFiles">
								{{ __("Clear all") }}
							</button>
						</div>
						<div
							v-for="(file, index) in localFiles"
							:key="index"
							class="local-file-item"
						>
							<component :is="getLocalFileIcon(file)" :size="20" class="icon" />
							<span class="name">{{ file.name }}</span>
							<span class="size">{{ formatSize(file.size) }}</span>
							<button class="btn-remove" @click="removeLocalFile(index)">
								<X :size="14" />
							</button>
						</div>
					</div>
				</div>

				<!-- File Manager Tab -->
				<div v-if="activeTab === 'files'" class="tab-content">
					<div class="search-bar">
						<Search :size="16" />
						<input
							v-model="fileSearch"
							:placeholder="__('Search files...')"
							@input="debouncedSearchFiles"
						/>
					</div>

					<!-- Breadcrumb -->
					<div class="breadcrumb">
						<button @click="navigateToFolder('Home')" class="breadcrumb-item">
							<Home :size="14" />
							<span>{{ __("Home") }}</span>
						</button>
						<template v-if="currentFolder !== 'Home'">
							<ChevronRight :size="14" />
							<span class="breadcrumb-item current">{{ currentFolder }}</span>
						</template>
					</div>

					<!-- Loading -->
					<div v-if="loadingFiles" class="loading-state">
						<Loader2 :size="24" class="spinner" />
						<span>{{ __("Loading files...") }}</span>
					</div>

					<!-- File list -->
					<div v-else class="file-list">
						<!-- Folders -->
						<div
							v-for="folder in fileFolders"
							:key="folder.name"
							class="file-item folder"
							@click="navigateToFolder(folder.file_name)"
						>
							<Folder :size="20" class="icon folder-icon" />
							<span class="name">{{ folder.file_name }}</span>
						</div>

						<!-- Files -->
						<div
							v-for="file in fileList"
							:key="file.name"
							class="file-item"
							:class="{ selected: selectedFile?.name === file.name }"
							@click="selectFile(file)"
							@dblclick="attachFile(file)"
						>
							<component :is="getFileIcon(file)" :size="20" class="icon" />
							<span class="name">{{ file.file_name }}</span>
							<span class="size">{{ formatSize(file.file_size) }}</span>
						</div>

						<!-- Empty state -->
						<div v-if="!fileFolders.length && !fileList.length" class="empty-state">
							<FileX :size="32" />
							<span>{{ __("No files found") }}</span>
						</div>
					</div>
				</div>

				<!-- Drive Tab -->
				<div v-if="activeTab === 'drive'" class="tab-content">
					<div class="search-bar">
						<Search :size="16" />
						<input
							v-model="driveSearch"
							:placeholder="__('Search Drive files...')"
							@input="debouncedSearchDrive"
						/>
					</div>

					<!-- Loading -->
					<div v-if="loadingDrive" class="loading-state">
						<Loader2 :size="24" class="spinner" />
						<span>{{ __("Loading Drive files...") }}</span>
					</div>

					<!-- Drive not installed -->
					<div v-else-if="driveNotInstalled" class="empty-state">
						<HardDrive :size="32" />
						<span>{{ __("Frappe Drive is not installed") }}</span>
					</div>

					<!-- Drive file list -->
					<div v-else class="file-list">
						<!-- Folders -->
						<div
							v-for="folder in driveFolders"
							:key="folder.name"
							class="file-item folder"
							@click="navigateToDriveFolder(folder.name)"
						>
							<Folder :size="20" class="icon folder-icon" />
							<span class="name">{{ folder.title }}</span>
						</div>

						<!-- Files -->
						<div
							v-for="file in driveFiles"
							:key="file.name"
							class="file-item"
							:class="{ selected: selectedDriveFile?.name === file.name }"
							@click="selectDriveFile(file)"
							@dblclick="attachDriveFile(file)"
						>
							<component :is="getDriveFileIcon(file)" :size="20" class="icon" />
							<span class="name">{{ file.title }}</span>
							<span class="size">{{ formatSize(file.file_size) }}</span>
						</div>

						<!-- Empty state -->
						<div v-if="!driveFolders.length && !driveFiles.length" class="empty-state">
							<FileX :size="32" />
							<span>{{ __("No files found") }}</span>
						</div>
					</div>
				</div>

				<!-- Document Tab -->
				<div v-if="activeTab === 'document'" class="tab-content">
					<!-- DocType selector -->
					<div class="doctype-selector">
						<label>{{ __("Document Type") }}</label>
						<select v-model="selectedDoctype" @change="resetDocSearch">
							<option value="">{{ __("Select a type...") }}</option>
							<option v-for="dt in doctypes" :key="dt.doctype" :value="dt.doctype">
								{{ dt.label }}
							</option>
						</select>
					</div>

					<!-- Document search -->
					<div v-if="selectedDoctype" class="search-bar">
						<Search :size="16" />
						<input
							v-model="docSearch"
							:placeholder="__('Search {0}...', [selectedDoctype])"
							@input="debouncedSearchDocs"
						/>
					</div>

					<!-- Loading -->
					<div v-if="loadingDocs" class="loading-state">
						<Loader2 :size="24" class="spinner" />
						<span>{{ __("Searching...") }}</span>
					</div>

					<!-- Document results -->
					<div v-else-if="selectedDoctype" class="document-list">
						<div
							v-for="doc in documentResults"
							:key="doc.value"
							class="document-item"
							:class="{ selected: selectedDocument?.value === doc.value }"
							@click="selectDocument(doc)"
							@dblclick="attachDocument(doc)"
						>
							<FileText :size="20" class="icon" />
							<div class="doc-info">
								<span class="doc-name">{{ doc.value }}</span>
								<span v-if="doc.description" class="doc-description">{{
									doc.description
								}}</span>
							</div>
							<button class="btn-attach-pdf" @click.stop="attachDocument(doc)">
								<FileDown :size="14" />
								{{ __("PDF") }}
							</button>
						</div>

						<!-- Empty state -->
						<div v-if="!documentResults.length && !loadingDocs" class="empty-state">
							<FileX :size="32" />
							<span>{{ __("No documents found") }}</span>
						</div>
					</div>

					<!-- Select doctype prompt -->
					<div v-else class="empty-state">
						<FileText :size="32" />
						<span>{{ __("Select a document type to search") }}</span>
					</div>
				</div>
			</div>

			<!-- Footer with actions -->
			<div class="picker-footer">
				<div class="selection-display" v-if="hasSelection">
					<div class="selection-badge" :class="selectionSource">
						<Check :size="14" />
						<span class="badge-label">
							<template v-if="selectionSource === 'local'">{{
								__("Local")
							}}</template>
							<template v-else-if="selectionSource === 'files'">{{
								__("Files")
							}}</template>
							<template v-else-if="selectionSource === 'drive'">{{
								__("Drive")
							}}</template>
							<template v-else-if="selectionSource === 'document'">{{
								__("PDF")
							}}</template>
						</span>
					</div>
					<div class="selection-details">
						<span class="selection-name">{{ selectionLabel }}</span>
						<span v-if="totalSelectionSize" class="selection-size">{{
							formatSize(totalSelectionSize)
						}}</span>
					</div>
				</div>
				<div v-else class="no-selection">
					<span>{{ __("No file selected") }}</span>
				</div>
				<div class="footer-actions">
					<button class="btn btn-secondary" @click="$emit('close')">
						{{ __("Cancel") }}
					</button>
					<button
						class="btn btn-primary"
						:disabled="!hasSelection || isAttaching"
						@click="attachSelected"
					>
						<Loader2 v-if="isAttaching" :size="14" class="spinner" />
						<span v-else>{{ __("Attach") }}</span>
					</button>
				</div>
			</div>
		</div>
	</div>
</template>

<script>
import {
	X,
	Search,
	Home,
	ChevronRight,
	Folder,
	File,
	FileText,
	FileImage,
	FileVideo,
	FileAudio,
	FileArchive,
	FileCode,
	FileSpreadsheet,
	FileX,
	FileDown,
	Paperclip,
	Loader2,
	HardDrive,
	Upload,
	Check,
} from "lucide-vue-next";

export default {
	name: "AttachmentPicker",

	components: {
		X,
		Search,
		Home,
		ChevronRight,
		Folder,
		File,
		FileText,
		FileImage,
		FileVideo,
		FileAudio,
		FileArchive,
		FileCode,
		FileSpreadsheet,
		FileX,
		FileDown,
		Paperclip,
		Loader2,
		HardDrive,
		Upload,
		Check,
	},

	props: {
		show: { type: Boolean, default: false },
		account: { type: String, required: true },
		hasDrive: { type: Boolean, default: true },
	},

	emits: ["close", "select"],

	data() {
		return {
			activeTab: "local",
			// Local upload
			localFiles: [],
			isDragging: false,
			// File Manager
			currentFolder: "Home",
			fileSearch: "",
			fileFolders: [],
			fileList: [],
			loadingFiles: false,
			selectedFile: null,
			// Drive
			currentDriveFolder: null,
			driveSearch: "",
			driveFolders: [],
			driveFiles: [],
			loadingDrive: false,
			selectedDriveFile: null,
			driveNotInstalled: false,
			// Documents
			doctypes: [],
			selectedDoctype: "",
			docSearch: "",
			documentResults: [],
			loadingDocs: false,
			selectedDocument: null,
			// General
			isAttaching: false,
			searchTimeout: null,
		};
	},

	computed: {
		availableTabs() {
			const tabs = [
				{ id: "local", label: this.__("Local"), icon: "Upload" },
				{ id: "files", label: this.__("Files"), icon: "Folder" },
				{ id: "document", label: this.__("Document"), icon: "FileText" },
			];

			if (this.hasDrive) {
				tabs.splice(2, 0, { id: "drive", label: this.__("Drive"), icon: "HardDrive" });
			}

			return tabs;
		},

		hasSelection() {
			return !!(
				this.localFiles.length ||
				this.selectedFile ||
				this.selectedDriveFile ||
				this.selectedDocument
			);
		},

		selectionLabel() {
			if (this.localFiles.length > 0) {
				if (this.localFiles.length === 1) {
					return this.localFiles[0].name;
				}
				return this.__("{0} files selected", [this.localFiles.length]);
			}
			if (this.selectedFile) {
				return this.selectedFile.file_name;
			}
			if (this.selectedDriveFile) {
				return this.selectedDriveFile.title;
			}
			if (this.selectedDocument) {
				return `${this.selectedDoctype}: ${this.selectedDocument.value}`;
			}
			return "";
		},

		selectionSource() {
			if (this.localFiles.length > 0) return "local";
			if (this.selectedFile) return "files";
			if (this.selectedDriveFile) return "drive";
			if (this.selectedDocument) return "document";
			return null;
		},

		totalSelectionSize() {
			if (this.localFiles.length > 0) {
				return this.localFiles.reduce((sum, f) => sum + f.size, 0);
			}
			if (this.selectedFile) return this.selectedFile.file_size || 0;
			if (this.selectedDriveFile) return this.selectedDriveFile.file_size || 0;
			return 0;
		},
	},

	watch: {
		show(newVal) {
			if (newVal) {
				this.initPicker();
			}
		},
		activeTab(newTab) {
			// Load data when switching tabs
			if (
				newTab === "files" &&
				this.fileList.length === 0 &&
				this.fileFolders.length === 0
			) {
				this.loadFiles();
			} else if (
				newTab === "drive" &&
				this.driveFiles.length === 0 &&
				this.driveFolders.length === 0 &&
				!this.driveNotInstalled
			) {
				this.loadDriveFiles();
			}
		},
	},

	methods: {
		async initPicker() {
			// Reset state
			this.localFiles = [];
			this.selectedFile = null;
			this.selectedDriveFile = null;
			this.selectedDocument = null;

			// Load data based on active tab
			if (this.activeTab === "files") {
				await this.loadFiles();
			} else if (this.activeTab === "drive") {
				await this.loadDriveFiles();
			}

			// Load doctypes for document tab
			await this.loadDoctypes();
		},

		// =====================================
		// LOCAL UPLOAD
		// =====================================

		triggerFileInput() {
			this.$refs.localFileInput?.click();
		},

		handleLocalFileSelect(event) {
			const files = Array.from(event.target.files);
			this.addLocalFiles(files);
			// Reset input to allow re-selecting same file
			event.target.value = "";
		},

		handleDrop(event) {
			this.isDragging = false;
			const files = Array.from(event.dataTransfer.files);
			this.addLocalFiles(files);
		},

		addLocalFiles(files) {
			const maxSize = 25 * 1024 * 1024; // 25 MB
			for (const file of files) {
				if (file.size > maxSize) {
					frappe.toast({
						message: this.__("{0} exceeds 25 MB limit", [file.name]),
						indicator: "orange",
					});
					continue;
				}
				// Avoid duplicates
				if (!this.localFiles.some((f) => f.name === file.name && f.size === file.size)) {
					this.localFiles.push(file);
				}
			}
			// Clear other selections when adding local files
			this.selectedFile = null;
			this.selectedDriveFile = null;
			this.selectedDocument = null;
		},

		removeLocalFile(index) {
			this.localFiles.splice(index, 1);
		},

		clearLocalFiles() {
			this.localFiles = [];
		},

		getLocalFileIcon(file) {
			const type = file.type?.toLowerCase() || "";
			const name = file.name?.toLowerCase() || "";

			if (type.startsWith("image/")) return "FileImage";
			if (type.startsWith("video/")) return "FileVideo";
			if (type.startsWith("audio/")) return "FileAudio";
			if (type === "application/pdf") return "FileText";
			if (
				type.includes("zip") ||
				type.includes("archive") ||
				/\.(zip|rar|7z|tar|gz)$/.test(name)
			)
				return "FileArchive";
			if (type.includes("spreadsheet") || /\.(xls|xlsx|csv)$/.test(name))
				return "FileSpreadsheet";
			if (type.includes("document") || /\.(doc|docx|txt|rtf)$/.test(name)) return "FileText";
			if (/\.(js|ts|py|html|css|json|xml)$/.test(name)) return "FileCode";
			return "File";
		},

		// =====================================
		// FILE MANAGER
		// =====================================

		async loadFiles() {
			this.loadingFiles = true;
			try {
				const response = await frappe.call({
					method: "frappe_webmail.webmail_api.get_file_manager_files",
					args: {
						folder: this.currentFolder,
						search: this.fileSearch || null,
					},
				});

				this.fileFolders = response.message?.folders || [];
				this.fileList = response.message?.files || [];
			} catch (error) {
				console.error("Failed to load files:", error);
				frappe.toast({ message: this.__("Failed to load files"), indicator: "red" });
			} finally {
				this.loadingFiles = false;
			}
		},

		navigateToFolder(folderName) {
			this.currentFolder = folderName;
			this.selectedFile = null;
			this.loadFiles();
		},

		selectFile(file) {
			this.selectedFile = file;
			// Clear other selections
			this.localFiles = [];
			this.selectedDriveFile = null;
			this.selectedDocument = null;
		},

		async attachFile(file) {
			this.selectedFile = file;
			await this.attachSelected();
		},

		debouncedSearchFiles() {
			clearTimeout(this.searchTimeout);
			this.searchTimeout = setTimeout(() => {
				this.loadFiles();
			}, 300);
		},

		getFileIcon(file) {
			const type = file.file_type?.toLowerCase() || "";
			const name = file.file_name?.toLowerCase() || "";

			if (type.includes("image") || /\.(jpg|jpeg|png|gif|svg|webp)$/.test(name)) {
				return "FileImage";
			}
			if (type.includes("video") || /\.(mp4|avi|mov|wmv|webm)$/.test(name)) {
				return "FileVideo";
			}
			if (type.includes("audio") || /\.(mp3|wav|ogg|flac)$/.test(name)) {
				return "FileAudio";
			}
			if (type.includes("pdf") || /\.pdf$/.test(name)) {
				return "FileText";
			}
			if (/\.(zip|rar|7z|tar|gz)$/.test(name)) {
				return "FileArchive";
			}
			if (/\.(js|ts|py|html|css|json|xml)$/.test(name)) {
				return "FileCode";
			}
			if (/\.(xls|xlsx|csv)$/.test(name)) {
				return "FileSpreadsheet";
			}
			if (/\.(doc|docx|txt|rtf)$/.test(name)) {
				return "FileText";
			}
			return "File";
		},

		// =====================================
		// DRIVE
		// =====================================

		async loadDriveFiles() {
			this.loadingDrive = true;
			this.driveNotInstalled = false;
			try {
				const response = await frappe.call({
					method: "frappe_webmail.webmail_api.get_drive_files",
					args: {
						folder: this.currentDriveFolder,
						search: this.driveSearch || null,
					},
				});

				if (response.message?.message?.includes("not installed")) {
					this.driveNotInstalled = true;
					this.driveFolders = [];
					this.driveFiles = [];
				} else {
					this.driveFolders = response.message?.folders || [];
					this.driveFiles = response.message?.files || [];
				}
			} catch (error) {
				console.error("Failed to load Drive files:", error);
				this.driveNotInstalled = true;
			} finally {
				this.loadingDrive = false;
			}
		},

		navigateToDriveFolder(folderName) {
			this.currentDriveFolder = folderName;
			this.selectedDriveFile = null;
			this.loadDriveFiles();
		},

		selectDriveFile(file) {
			this.selectedDriveFile = file;
			// Clear other selections
			this.localFiles = [];
			this.selectedFile = null;
			this.selectedDocument = null;
		},

		async attachDriveFile(file) {
			this.selectedDriveFile = file;
			await this.attachSelected();
		},

		debouncedSearchDrive() {
			clearTimeout(this.searchTimeout);
			this.searchTimeout = setTimeout(() => {
				this.loadDriveFiles();
			}, 300);
		},

		getDriveFileIcon(file) {
			const type = file.mime_type?.toLowerCase() || "";
			const name = file.title?.toLowerCase() || "";

			if (type.includes("image")) return "FileImage";
			if (type.includes("video")) return "FileVideo";
			if (type.includes("audio")) return "FileAudio";
			if (type.includes("pdf")) return "FileText";
			if (type.includes("zip") || type.includes("archive")) return "FileArchive";
			if (type.includes("spreadsheet") || /\.(xls|xlsx|csv)$/.test(name))
				return "FileSpreadsheet";
			if (type.includes("document") || type.includes("text")) return "FileText";
			return "File";
		},

		// =====================================
		// DOCUMENTS
		// =====================================

		async loadDoctypes() {
			try {
				const response = await frappe.call({
					method: "frappe_webmail.webmail_api.get_printable_doctypes",
				});
				this.doctypes = response.message || [];
			} catch (error) {
				console.error("Failed to load doctypes:", error);
			}
		},

		resetDocSearch() {
			this.docSearch = "";
			this.documentResults = [];
			this.selectedDocument = null;
			// Load recent documents when doctype is selected
			if (this.selectedDoctype) {
				this.loadRecentDocuments();
			}
		},

		async loadRecentDocuments() {
			if (!this.selectedDoctype) return;

			this.loadingDocs = true;
			try {
				const response = await frappe.call({
					method: "frappe_webmail.webmail_api.get_recent_documents",
					args: {
						doctype: this.selectedDoctype,
						limit: 10,
					},
				});
				this.documentResults = response.message || [];
			} catch (error) {
				console.error("Failed to load recent documents:", error);
				this.documentResults = [];
			} finally {
				this.loadingDocs = false;
			}
		},

		async searchDocuments() {
			if (!this.selectedDoctype) {
				this.documentResults = [];
				return;
			}

			// If no search text, load recent documents
			if (!this.docSearch) {
				await this.loadRecentDocuments();
				return;
			}

			this.loadingDocs = true;
			try {
				const response = await frappe.call({
					method: "frappe_webmail.webmail_api.search_documents",
					args: {
						doctype: this.selectedDoctype,
						search_text: this.docSearch,
					},
				});
				this.documentResults = response.message || [];
			} catch (error) {
				console.error("Failed to search documents:", error);
				this.documentResults = [];
			} finally {
				this.loadingDocs = false;
			}
		},

		debouncedSearchDocs() {
			clearTimeout(this.searchTimeout);
			this.searchTimeout = setTimeout(() => {
				this.searchDocuments();
			}, 300);
		},

		selectDocument(doc) {
			this.selectedDocument = doc;
			// Clear other selections
			this.localFiles = [];
			this.selectedFile = null;
			this.selectedDriveFile = null;
		},

		async attachDocument(doc) {
			this.selectedDocument = doc;
			await this.attachSelected();
		},

		// =====================================
		// ATTACH SELECTED
		// =====================================

		async attachSelected() {
			if (!this.hasSelection) return;

			this.isAttaching = true;

			try {
				// Local files
				if (this.localFiles.length > 0) {
					const attachments = [];
					for (const file of this.localFiles) {
						const content = await this.fileToBase64(file);
						attachments.push({
							source: "local",
							filename: file.name,
							content: content,
							content_type: file.type || "application/octet-stream",
							size: file.size,
						});
					}
					// Emit each attachment
					for (const attachment of attachments) {
						this.$emit("select", attachment);
					}
					this.$emit("close");
					return;
				}

				let attachment = null;

				if (this.selectedFile) {
					// Attach from File Manager
					const response = await frappe.call({
						method: "frappe_webmail.webmail_api.get_file_content",
						args: { file_url: this.selectedFile.file_url },
					});

					attachment = {
						source: "file",
						filename: response.message.filename,
						content: response.message.content,
						content_type: response.message.content_type,
						size: response.message.size,
					};
				} else if (this.selectedDriveFile) {
					// Attach from Drive
					const response = await frappe.call({
						method: "frappe_webmail.webmail_api.get_drive_file_content",
						args: { entity_name: this.selectedDriveFile.name },
					});

					attachment = {
						source: "drive",
						filename: response.message.filename,
						content: response.message.content,
						content_type: response.message.content_type,
						size: response.message.size,
					};
				} else if (this.selectedDocument) {
					// Generate and attach PDF
					const response = await frappe.call({
						method: "frappe_webmail.webmail_api.generate_document_pdf",
						args: {
							doctype: this.selectedDoctype,
							docname: this.selectedDocument.value,
						},
					});

					attachment = {
						source: "document",
						filename: response.message.filename,
						content: response.message.content,
						content_type: response.message.content_type,
						size: response.message.size,
						doctype: this.selectedDoctype,
						docname: this.selectedDocument.value,
					};
				}

				if (attachment) {
					this.$emit("select", attachment);
					this.$emit("close");
				}
			} catch (error) {
				console.error("Failed to attach file:", error);
				frappe.toast({
					message: this.__("Failed to attach file: {0}", [error.message || error]),
					indicator: "red",
				});
			} finally {
				this.isAttaching = false;
			}
		},

		fileToBase64(file) {
			return new Promise((resolve, reject) => {
				const reader = new FileReader();
				reader.onload = () => {
					// Remove the data:*/*;base64, prefix
					const base64 = reader.result.split(",")[1];
					resolve(base64);
				};
				reader.onerror = reject;
				reader.readAsDataURL(file);
			});
		},

		// =====================================
		// UTILS
		// =====================================

		formatSize(bytes) {
			if (!bytes) return "";
			if (bytes < 1024) return bytes + " B";
			if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
			return (bytes / (1024 * 1024)).toFixed(1) + " MB";
		},
	},
};
</script>

<style scoped>
.attachment-picker-overlay {
	position: fixed;
	top: 0;
	left: 0;
	right: 0;
	bottom: 0;
	background: rgba(0, 0, 0, 0.5);
	display: flex;
	align-items: center;
	justify-content: center;
	z-index: 1050;
}

.attachment-picker-modal {
	background: var(--card-bg, white);
	border-radius: 8px;
	width: 90%;
	max-width: 600px;
	max-height: 80vh;
	display: flex;
	flex-direction: column;
	box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
}

.picker-header {
	display: flex;
	justify-content: space-between;
	align-items: center;
	padding: 16px 20px;
	border-bottom: 1px solid var(--border-color, #e5e5e5);
}

.picker-header h3 {
	margin: 0;
	font-size: 16px;
	font-weight: 600;
	color: var(--text-color, #333);
}

.btn-close {
	background: none;
	border: none;
	cursor: pointer;
	padding: 4px;
	color: var(--text-muted, #8d99a6);
	border-radius: 4px;
}

.btn-close:hover {
	background: var(--bg-gray, #eee);
	color: var(--text-color, #333);
}

.picker-tabs {
	display: flex;
	gap: 4px;
	padding: 8px 16px;
	background: var(--bg-light-gray, #f8f9fa);
	border-bottom: 1px solid var(--border-color, #e5e5e5);
}

.picker-tabs button {
	display: flex;
	align-items: center;
	gap: 6px;
	padding: 8px 16px;
	border: none;
	background: transparent;
	cursor: pointer;
	font-size: 13px;
	color: var(--text-muted, #8d99a6);
	border-radius: 4px;
	transition: all 0.15s ease;
}

.picker-tabs button:hover {
	background: var(--bg-gray, #eee);
	color: var(--text-color, #333);
}

.picker-tabs button.active {
	background: var(--primary-color, #2490ef);
	color: white;
}

.picker-content {
	flex: 1;
	overflow: hidden;
	display: flex;
	flex-direction: column;
	min-height: 0;
}

.tab-content {
	flex: 1;
	display: flex;
	flex-direction: column;
	overflow: hidden;
}

.search-bar {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 12px 16px;
	border-bottom: 1px solid var(--border-color, #e5e5e5);
	background: var(--card-bg, white);
}

.search-bar input {
	flex: 1;
	border: none;
	outline: none;
	font-size: 14px;
	background: transparent;
}

.breadcrumb {
	display: flex;
	align-items: center;
	gap: 4px;
	padding: 8px 16px;
	background: var(--bg-light-gray, #f8f9fa);
	font-size: 13px;
	border-bottom: 1px solid var(--border-color, #e5e5e5);
}

.breadcrumb-item {
	display: flex;
	align-items: center;
	gap: 4px;
	color: var(--primary-color, #2490ef);
	background: none;
	border: none;
	cursor: pointer;
	padding: 2px 6px;
	border-radius: 4px;
	font-size: 13px;
}

.breadcrumb-item:hover {
	background: var(--bg-gray, #eee);
}

.breadcrumb-item.current {
	color: var(--text-color, #333);
	cursor: default;
}

.file-list,
.document-list {
	flex: 1;
	overflow-y: auto;
	padding: 8px;
}

.file-item,
.document-item {
	display: flex;
	align-items: center;
	gap: 12px;
	padding: 10px 12px;
	border-radius: 6px;
	cursor: pointer;
	transition: background 0.15s ease;
}

.file-item:hover,
.document-item:hover {
	background: var(--bg-light-gray, #f8f9fa);
}

.file-item.selected,
.document-item.selected {
	background: var(--subtle-accent, rgba(36, 144, 239, 0.1));
	border: 1px solid var(--primary-color, #2490ef);
}

.file-item .icon {
	color: var(--text-muted, #8d99a6);
	flex-shrink: 0;
}

.file-item.folder .icon,
.folder-icon {
	color: var(--yellow-500, #f0c000);
}

.file-item .name {
	flex: 1;
	font-size: 14px;
	color: var(--text-color, #333);
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.file-item .size {
	font-size: 12px;
	color: var(--text-muted, #8d99a6);
	flex-shrink: 0;
}

.document-item .doc-info {
	flex: 1;
	display: flex;
	flex-direction: column;
	gap: 2px;
	min-width: 0;
}

.document-item .doc-name {
	font-size: 14px;
	color: var(--text-color, #333);
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.document-item .doc-description {
	font-size: 12px;
	color: var(--text-muted, #8d99a6);
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.btn-attach-pdf {
	display: flex;
	align-items: center;
	gap: 4px;
	padding: 4px 10px;
	font-size: 12px;
	color: var(--primary-color, #2490ef);
	background: transparent;
	border: 1px solid var(--primary-color, #2490ef);
	border-radius: 4px;
	cursor: pointer;
	white-space: nowrap;
}

.btn-attach-pdf:hover {
	background: var(--primary-color, #2490ef);
	color: white;
}

.doctype-selector {
	padding: 12px 16px;
	border-bottom: 1px solid var(--border-color, #e5e5e5);
}

.doctype-selector label {
	display: block;
	font-size: 12px;
	color: var(--text-muted, #8d99a6);
	margin-bottom: 6px;
}

.doctype-selector select {
	width: 100%;
	padding: 8px 12px;
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 4px;
	font-size: 14px;
	background: var(--card-bg, white);
}

.loading-state,
.empty-state {
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	gap: 12px;
	padding: 40px;
	color: var(--text-muted, #8d99a6);
}

.spinner {
	animation: spin 1s linear infinite;
}

@keyframes spin {
	from {
		transform: rotate(0deg);
	}
	to {
		transform: rotate(360deg);
	}
}

/* Local Upload Tab */
.local-tab {
	padding: 16px;
}

.drop-zone {
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	gap: 12px;
	padding: 40px 20px;
	border: 2px dashed var(--border-color, #e5e5e5);
	border-radius: 8px;
	cursor: pointer;
	transition: all 0.2s ease;
	background: var(--bg-light-gray, #f8f9fa);
}

.drop-zone:hover {
	border-color: var(--primary-color, #2490ef);
	background: rgba(36, 144, 239, 0.05);
}

.drop-zone.dragging {
	border-color: var(--primary-color, #2490ef);
	background: rgba(36, 144, 239, 0.1);
}

.drop-zone .drop-icon {
	color: var(--text-muted, #8d99a6);
}

.drop-zone:hover .drop-icon,
.drop-zone.dragging .drop-icon {
	color: var(--primary-color, #2490ef);
}

.drop-zone .drop-text {
	margin: 0;
	font-size: 14px;
	color: var(--text-color, #333);
}

.drop-zone .drop-hint {
	margin: 0;
	font-size: 12px;
	color: var(--text-muted, #8d99a6);
}

.local-files-list {
	margin-top: 16px;
}

.local-files-header {
	display: flex;
	justify-content: space-between;
	align-items: center;
	margin-bottom: 8px;
	padding: 0 4px;
}

.local-files-header span {
	font-size: 12px;
	font-weight: 600;
	color: var(--text-muted, #8d99a6);
	text-transform: uppercase;
}

.btn-clear-all {
	background: none;
	border: none;
	font-size: 12px;
	color: var(--red-500, #e53e3e);
	cursor: pointer;
	padding: 2px 6px;
	border-radius: 4px;
}

.btn-clear-all:hover {
	background: rgba(229, 62, 62, 0.1);
}

.local-file-item {
	display: flex;
	align-items: center;
	gap: 10px;
	padding: 8px 12px;
	background: var(--card-bg, white);
	border: 1px solid var(--border-color, #e5e5e5);
	border-radius: 6px;
	margin-bottom: 6px;
}

.local-file-item .icon {
	color: var(--primary-color, #2490ef);
	flex-shrink: 0;
}

.local-file-item .name {
	flex: 1;
	font-size: 13px;
	color: var(--text-color, #333);
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.local-file-item .size {
	font-size: 12px;
	color: var(--text-muted, #8d99a6);
	flex-shrink: 0;
}

.btn-remove {
	background: none;
	border: none;
	padding: 4px;
	cursor: pointer;
	color: var(--text-muted, #8d99a6);
	border-radius: 4px;
}

.btn-remove:hover {
	background: var(--red-50, #fee2e2);
	color: var(--red-500, #e53e3e);
}

/* Footer */
.picker-footer {
	display: flex;
	justify-content: space-between;
	align-items: center;
	padding: 12px 16px;
	border-top: 1px solid var(--border-color, #e5e5e5);
	background: var(--bg-light-gray, #f8f9fa);
	border-radius: 0 0 8px 8px;
	gap: 12px;
	flex-shrink: 0;
	min-height: 60px;
}

.selection-display {
	display: flex;
	align-items: center;
	gap: 10px;
	flex: 1;
	min-width: 0;
}

.selection-badge {
	display: flex;
	align-items: center;
	gap: 4px;
	padding: 4px 10px;
	border-radius: 20px;
	font-size: 11px;
	font-weight: 600;
	text-transform: uppercase;
	flex-shrink: 0;
}

.selection-badge.local {
	background: var(--green-100, #dcfce7);
	color: var(--green-700, #15803d);
}

.selection-badge.files {
	background: var(--blue-100, #dbeafe);
	color: var(--blue-700, #1d4ed8);
}

.selection-badge.drive {
	background: var(--purple-100, #f3e8ff);
	color: var(--purple-700, var(--wm-accent));
}

.selection-badge.document {
	background: var(--orange-100, #ffedd5);
	color: var(--orange-700, #c2410c);
}

.selection-details {
	display: flex;
	flex-direction: column;
	gap: 2px;
	min-width: 0;
}

.selection-name {
	font-size: 13px;
	font-weight: 500;
	color: var(--text-color, #333);
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.selection-size {
	font-size: 11px;
	color: var(--text-muted, #8d99a6);
}

.no-selection {
	flex: 1;
	font-size: 13px;
	color: var(--text-muted, #8d99a6);
	font-style: italic;
}

.footer-actions {
	display: flex;
	gap: 8px;
}

.footer-actions .btn {
	padding: 8px 16px;
	border-radius: 6px;
	font-size: 14px;
	cursor: pointer;
	display: flex;
	align-items: center;
	gap: 6px;
}

.btn-secondary {
	background: var(--card-bg, white);
	border: 1px solid var(--border-color, #e5e5e5);
	color: var(--text-color, #333);
}

.btn-secondary:hover {
	background: var(--bg-gray, #eee);
}

.btn-primary {
	background: var(--primary-color, #2490ef);
	border: 1px solid var(--primary-color, #2490ef);
	color: white;
}

.btn-primary:hover:not(:disabled) {
	background: var(--primary-dark, #1a7fd4);
}

.btn-primary:disabled {
	opacity: 0.6;
	cursor: not-allowed;
}
</style>
