"""
DocManager - Tag-Baum (linkes Panel)

Zeigt die hierarchische Tag-Struktur als QTreeWidget.
Sendet ein Signal wenn ein Tag ausgewählt wird.
"""
from typing import Optional
from PyQt6.QtWidgets import (QTreeWidget, QTreeWidgetItem, QMenu,
                              QInputDialog, QMessageBox)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QIcon

import config
from database.db import Database


class TagTree(QTreeWidget):
    # Signale
    tag_selected = pyqtSignal(object)   # tag_id (int) oder None (alle)
    tag_renamed = pyqtSignal(int, str)  # tag_id, new_name

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.setHeaderLabel("Kategorien")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.itemClicked.connect(self._on_item_clicked)
        self.setMinimumWidth(160)

        # Gemerkter Faltstatus: Menge expandierter tag_ids (aus Einstellungen)
        settings = config.load_settings()
        self._expanded_ids: set = set(settings.get("expanded_tags", []))
        self.itemExpanded.connect(self._on_item_expanded)
        self.itemCollapsed.connect(self._on_item_collapsed)

        self.reload()

    def reload(self) -> None:
        """Baut den Baum neu auf."""
        self.blockSignals(True)
        self.clear()
        # "Alle Dokumente"-Eintrag
        all_item = QTreeWidgetItem(self, ["Alle Dokumente"])
        all_item.setData(0, Qt.ItemDataRole.UserRole, None)
        self._load_tags(None, self)
        # Default eingeklappt; gemerkten Faltstatus wiederherstellen
        self._restore_expansion()
        self.blockSignals(False)

    def _load_tags(self, parent_id: Optional[int],
                   parent_widget) -> None:
        """Lädt Tags rekursiv."""
        if parent_id is None:
            tags = self.db.get_root_tags()
        else:
            tags = self.db.get_child_tags(parent_id)
        for tag in tags:
            item = QTreeWidgetItem(parent_widget, [tag["name"]])
            item.setData(0, Qt.ItemDataRole.UserRole, tag["id"])
            self._load_tags(tag["id"], item)

    def _on_item_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        tag_id = item.data(0, Qt.ItemDataRole.UserRole)
        self.tag_selected.emit(tag_id)

    # ── Faltstatus ──────────────────────────────────────────────────────────────

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        tag_id = item.data(0, Qt.ItemDataRole.UserRole)
        if tag_id is not None:
            self._expanded_ids.add(tag_id)

    def _on_item_collapsed(self, item: QTreeWidgetItem) -> None:
        tag_id = item.data(0, Qt.ItemDataRole.UserRole)
        if tag_id is not None:
            self._expanded_ids.discard(tag_id)

    def _restore_expansion(self) -> None:
        """Stellt den gemerkten Faltstatus anhand der tag_ids wieder her."""
        for item in self._iter_items(self.invisibleRootItem()):
            tag_id = item.data(0, Qt.ItemDataRole.UserRole)
            if tag_id is not None and tag_id in self._expanded_ids:
                item.setExpanded(True)

    def save_expansion_state(self) -> None:
        """Persistiert den aktuellen Faltstatus in den Einstellungen."""
        settings = config.load_settings()
        settings["expanded_tags"] = sorted(self._expanded_ids)
        config.save_settings(settings)

    def _show_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        menu = QMenu(self)

        if item and item.data(0, Qt.ItemDataRole.UserRole) is not None:
            tag_id = item.data(0, Qt.ItemDataRole.UserRole)
            rename_action = menu.addAction("Umbenennen")
            add_child_action = menu.addAction("Unter-Kategorie hinzufügen")
            menu.addSeparator()
            delete_action = menu.addAction("Löschen (wenn leer)")

            action = menu.exec(self.mapToGlobal(pos))
            if action == rename_action:
                self._rename_tag(item, tag_id)
            elif action == add_child_action:
                self._add_child_tag(item, tag_id)
            elif action == delete_action:
                self.db.delete_tag_if_empty(tag_id)
                self.reload()
        else:
            add_action = menu.addAction("Neue Kategorie")
            action = menu.exec(self.mapToGlobal(pos))
            if action == add_action:
                self._add_root_tag()

    def _rename_tag(self, item: QTreeWidgetItem, tag_id: int) -> None:
        old_name = item.text(0)
        name, ok = QInputDialog.getText(
            self, "Umbenennen", "Neuer Name:", text=old_name
        )
        if ok and name.strip():
            from database.db import Database
            assert self.db.conn
            self.db.conn.execute(
                "UPDATE tags SET name=? WHERE id=?", (name.strip(), tag_id)
            )
            self.db.conn.commit()
            self.reload()

    def _add_child_tag(self, _item: QTreeWidgetItem, parent_id: int) -> None:
        name, ok = QInputDialog.getText(
            self, "Unter-Kategorie", "Name der Unter-Kategorie:"
        )
        if ok and name.strip():
            self.db.get_or_create_tag(name.strip(), parent_id)
            self.reload()

    def _add_root_tag(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Neue Kategorie", "Name der Kategorie:"
        )
        if ok and name.strip():
            self.db.get_or_create_tag(name.strip(), None)
            self.reload()

    def select_tag_by_id(self, tag_id: Optional[int]) -> None:
        """Programmatisch einen Tag auswählen."""
        iterator = self._iter_items(self.invisibleRootItem())
        for item in iterator:
            if item.data(0, Qt.ItemDataRole.UserRole) == tag_id:
                self.setCurrentItem(item)
                return

    def _iter_items(self, root):
        for i in range(root.childCount()):
            child = root.child(i)
            yield child
            yield from self._iter_items(child)
