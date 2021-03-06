#!/usr/bin/env python
import sys
import signal
import argparse
import time
import threading
import os
import os.path
import stat
import hashlib

#signal.signal(signal.SIGINT, signal.SIG_DFL)

def formatTimeStamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def logDebug(s):
    sys.stderr.write(formatTimeStamp() + " " + s + "\n")
    sys.stderr.flush()

def logError(s):
    # TODO: do something more proper
    logDebug("ERROR: " + s)

class ConfigurationLocation:
    def __init__(self, s_baseDirectoryPath = None):
        self.s_baseDirectoryPath = s_baseDirectoryPath

class Configuration:
    def __init__(self):
        self.a_locations = []
        self.i_tcpPort = 8847

class FileChange:
    def __init__(self):
        pass

class FileChangeProdider:
    def __init__(self):
        pass

    def getChanges(self):
        return []

def mainUI(cfg):
    from PyQt5 import QtCore
    from PyQt5 import QtWidgets
    from PyQt5 import QtGui
    app = QtWidgets.QApplication(sys.argv)

    w = QtWidgets.QWidget()

    def onQuit():
        QtCore.QCoreApplication.instance().quit()

    class SystemTrayIcon(QtWidgets.QSystemTrayIcon):
        def __init__(self, icon, parent=None):
            QtWidgets.QSystemTrayIcon.__init__(self, icon, parent)
            menu = QtWidgets.QMenu(parent)
            exitAction = menu.addAction(QtGui.QIcon("resources/quit.ico"), "E&xit")
            exitAction.triggered.connect(onQuit)
            self.setContextMenu(menu)

    trayIcon = SystemTrayIcon(QtGui.QIcon("resources/main.ico"), w)
    trayIcon.show()

    i_result = app.exec_()
    trayIcon.hide()
    del app
    sys.exit(i_result)

class Atom:
    def __init__(self):
        # properties stored in database
        self.i_id = None
        self.i_parentId = None
        self.s_name = None
        self.f_lastModificationTimeStamp = None
        self.s_contentHash = None
        # runtime properties
        self.s_localPath = None

    def insertIntoDB(self, db):
        qi = QtSql.QSqlQuery(db);
        qi.prepare("INSERT INTO atoms(name, parentId, lastModification, contentSize, contentHash) VALUES(?, ?, ?, ?, ?)")
        qi.bindValue(0, self.s_name)
        qi.bindValue(1, self.i_parentId)
        qi.bindValue(2, self.f_lastModificationTimeStamp)
        qi.bindValue(3, self.i_contentSize if hasattr(self, 'i_contentSize') else -1)
        qi.bindValue(4, self.s_contentHash)
        if qi.exec_():
            self.i_id = qi.lastInsertId()
            qi.finish()
        else:
            logError("Failed to execute atom insert query: %s" % str(qi.lastError().text()))

    def updateInDB(self, db):
        qu = QtSql.QSqlQuery(db);
        qu.prepare("UPDATE atoms SET name = ?, parentId = ?, lastModification = ?, contentSize = ?, contentHash = ? WHERE id = ?")
        qu.bindValue(0, self.s_name)
        qu.bindValue(1, self.i_parentId)
        qu.bindValue(2, self.f_lastModificationTimeStamp)
        qu.bindValue(3, self.i_contentSize if hasattr(self, 'i_contentSize') else -1)
        qu.bindValue(4, self.s_contentHash)
        qu.bindValue(5, self.i_id)
        if qu.exec_():
            qu.finish()
        else:
            logError("Failed to execute atom update query: %s" % str(qu.lastError().text()))

    def removeFromDB(self, db):
        def recursiveDelete(i_id):
            q = QtSql.QSqlQuery(db)
            q.prepare("SELECT id FROM atoms WHERE parentId = ?")
            q.bindValue(0, i_id)
            if q.exec_():
                try:
                    while q.next():
                        r = q.record()
                        recursiveDelete(r.field(0).value())
                finally:
                    q.finish()
            else:
                logError("Failed to execute atom cascade delete query: %s" % str(q.lastError().text()))

            qd = QtSql.QSqlQuery(db);
            qd.prepare("DELETE FROM atoms WHERE id = ?")
            qd.bindValue(0, i_id)
            if qd.exec_():
                qd.finish()
            else:
                logError("Failed to execute atom delete query: %s" % str(qd.lastError().text()))

        recursiveDelete(self.i_id)

    @staticmethod
    def initDBStructures(db):
        q = QtSql.QSqlQuery(db)
        logDebug("Creating table \"atoms\"")
        if q.exec("""
                CREATE TABLE atoms(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parentId INTEGER,
                    name TEXT,
                    lastModification REAL,
                    contentSize INTEGER,
                    contentHash TEXT
                );"""):
            q.finish()
        else:
            logError("Failed to create table \"atoms\": %s" % str(q.lastError().text()))

        logDebug("Creating index \"atomParents\"")
        if(q.exec("CREATE INDEX atomParents ON atoms(parentId)")):
            q.finish()
        else:
            logError("Failed to create index \"atomParents\": %s" % str(q.lastError().text()))

    @staticmethod
    def listAtomsFromDBForParent(db, i_parentId = None):
        q = QtSql.QSqlQuery(db);
        if i_parentId is not None:
            q.prepare("SELECT * FROM atoms WHERE parentId = ?")
            q.bindValue(0, i_parentId)
        else:
            q.prepare("SELECT * FROM atoms WHERE parentId IS NULL")
        a_result = []
        if q.exec_():
            try:
                while q.next():
                    r = q.record()
                    a_result.append(Atom._createAtomFromDBRecord(r))
            finally:
                q.finish()
        return a_result

    def createAtomFromDB(db, i_id = None):
        q = QtSql.QSqlQuery(db);
        if i_id is None:
            return DirectoryAtom() # top directory
        else:
            q.prepare("SELECT * FROM atoms WHERE id = ?")
            q.bindValue(0, i_id)
        if q.exec_():
            try:
                if q.next():
                    return Atom._createAtomFromDBRecord(r)
            finally:
                q.finish()
        return None

    @staticmethod
    def _createAtomFromDBRecord(r):
        i_size = int(r.field("contentSize").value())
        if i_size < 0:
            atom = DirectoryAtom()
        else:
            atom = FileAtom()
            atom.i_contentSize = i_size
        atom.i_id = int(r.field("id").value())
        atom.s_name = str(r.field("name").value())
        v = r.field("parentId").value()
        atom.i_parentId = int(v) if len(str(v)) > 0 else None
        v = r.field("lastModification").value()
        atom.f_lastModificationTimeStamp = float(v) if len(str(v)) > 0 else None
        atom.s_contentHash = str(r.field("contentHash").value())
        return atom

class DirectoryAtom(Atom):
    def __init__(self):
        Atom.__init__(self)

class FileAtom(Atom):
    def __init__(self):
        Atom.__init__(self)
        self.i_contentSize = None

class FileChangeDiscoveryThread(threading.Thread):

    class LocationData:
        def __init__(self):
            self.db = None
            self.atom = None

    def __init__(self, cfg):
        threading.Thread.__init__(self)
        self.cfg = cfg
        self.lock = threading.Lock()
        self.quitEvent = threading.Event()
        self.d_locationToData = {}
        logDebug("Available SQL drivers: %s" % str(QtSql.QSqlDatabase.drivers()))
        for loc in cfg.a_locations:
            logDebug("Opening database for %s" % loc.s_baseDirectoryPath)
            db = QtSql.QSqlDatabase().addDatabase("QSQLITE", "db-conn-" + loc.s_baseDirectoryPath)
            db.setDatabaseName(os.path.join(loc.s_baseDirectoryPath, ".atomibox.sqlite"));
            if db.open():
                #logDebug("Available database tables: %s" % str(db.tables()))
                r = db.driver().record("atoms")
                as_columnNames = [str(r.fieldName(i)) for i in range(0, r.count())]
                #logDebug("Current columns: %s" % ", ".join(as_columnNames))
                #if len(as_columnNames) and 'parent' not in as_columnNames:
                #    # do column upgrade if needed
                if len(as_columnNames) == 0:
                    Atom.initDBStructures(db)

                atom = DirectoryAtom()
                atom.s_name = loc.s_baseDirectoryPath
                atom.s_localPath = os.path.abspath(loc.s_baseDirectoryPath)

                locationData = FileChangeDiscoveryThread.LocationData()
                locationData.db = db
                locationData.atom = atom
                self.d_locationToData[loc.s_baseDirectoryPath] = locationData

            else:
                logError("Failed to open database: %s" % str(db.lastError().text()))

    def __del__(self):
        # make sure all databases are close when this object is deleted
        for s, locationData in self.d_locationToData.items():
            logDebug("Closing database for %s" % s)
            locationData.db.close()

    def run(self):
        logDebug("FileChangeDiscoveryThread starts...")
        i_counter = 1000
        while not self.quitEvent.is_set(): # .wait(timeout)
            logDebug("FileChangeDiscoveryThread loops...")
            time.sleep(1)

            if i_counter < 3:
                i_counter += 1
                continue

            i_counter = 0
            for loc in cfg.a_locations:
                locationData = self.d_locationToData[loc.s_baseDirectoryPath]
                self.scanDirectory(locationData.db, locationData.atom, 0)

            # TODO: this code is here just for debugging
            #q = QtSql.QSqlQuery(locationData.db);
            #q.exec("SELECT * FROM atoms")
            #while q.next():
            #    r = q.record()
            #    s = ", ".join([str(r.field(i).value()) for i in range(0, r.count())])
            #    logDebug("ROW %s" % s)

        logDebug("FileChangeDiscoveryThread quits...")

    def scanDirectory(self, db, directoryAtom, i_currentDepth):
        if i_currentDepth == 0:
            logDebug("Scanning %s" % directoryAtom.s_localPath) 

        # build list actual files and directories here
        a_currentAtoms = []
        for s_name in os.listdir(directoryAtom.s_localPath):
            if s_name == "." or s_name == ".." or (i_currentDepth == 0 and s_name == ".atomibox.sqlite"):
                continue
            s_path = os.path.join(directoryAtom.s_localPath, s_name)
            t_stat = os.stat(s_path)

            # create temporary atom object
            if stat.S_ISDIR(t_stat.st_mode):
                atom = DirectoryAtom()
            else:
                atom = FileAtom()
                atom.i_contentSize = t_stat.st_size
            atom.s_name = s_name
            atom.i_parentId = directoryAtom.i_id
            atom.f_lastModificationTimeStamp = t_stat.st_mtime
            atom.s_localPath = s_path

            a_currentAtoms.append(atom)

        d_nameToCurrentAtoms = {}
        for currentAtom in a_currentAtoms:
            d_nameToCurrentAtoms[currentAtom.s_name] = currentAtom

        a_recordedAtoms = Atom.listAtomsFromDBForParent(db, directoryAtom.i_id)
        d_nameToRecordedAtoms = {}
        for recordedAtom in a_recordedAtoms:
            d_nameToRecordedAtoms[recordedAtom.s_name] = recordedAtom

        # now dive into subdirectories
        for atom in a_currentAtoms:
            if isinstance(atom, DirectoryAtom):
                if atom.s_name in d_nameToRecordedAtoms:
                    atom = d_nameToRecordedAtoms[atom.s_name]
                    atom.s_localPath = os.path.join(directoryAtom.s_localPath, atom.s_name)
                else:
                    # EVENT: new directory atom
                    atom.insertIntoDB(db)
                    logDebug("EVENT: detected new directory %s in #%s -> created #%d" % (
                            atom.s_name, str(directoryAtom.i_id), atom.i_id))
                    d_nameToRecordedAtoms[atom.s_name] = atom
                assert atom.i_id is not None
                assert atom.s_localPath is not None
                self.scanDirectory(db, atom, i_currentDepth + 1)

        for atom in a_currentAtoms:
            recordedAtom = d_nameToRecordedAtoms[atom.s_name] if atom.s_name in d_nameToRecordedAtoms else None
            #if recordedAtom is not None:
            #    logDebug("Record for %s FOUND in #%s as #%d" % (
            #            atom.s_name, str(directoryAtom.i_id), atom.i_id))
            if isinstance(atom, FileAtom) and isinstance(recordedAtom, FileAtom):
                # file record found
                if isinstance(recordedAtom, FileAtom) and isinstance(atom, FileAtom):
                    if recordedAtom.i_contentSize != atom.i_contentSize \
                            or recordedAtom.f_lastModificationTimeStamp != atom.f_lastModificationTimeStamp:
                        atom.s_contentHash = self.hashFileContent(atom.s_localPath)
                        atom.i_id = recordedAtom.i_id
                        atom.updateInDB(db)
                        logDebug("EVENT: detected content modification in file %s (%s->%s) in #%s" % (
                                atom.s_name, recordedAtom.s_contentHash, atom.s_contentHash, str(directoryAtom.i_id)))
            if recordedAtom is None:
                assert isinstance(atom, FileAtom)
                # EVENT: new file atom
                atom.s_contentHash = self.hashFileContent(atom.s_localPath)
                atom.insertIntoDB(db)
                d_nameToRecordedAtoms[atom.s_name] = atom
                logDebug("EVENT: detected new file %s (%s) in #%s -> created #%d" % (
                        atom.s_name, atom.s_contentHash, str(directoryAtom.i_id), atom.i_id))

        for recordedAtom in a_recordedAtoms:
            if recordedAtom.s_name not in d_nameToCurrentAtoms:
                # EVENT: deleted atom
                recordedAtom.removeFromDB(db)
                logDebug("EVENT: detected removal of atom %s #%d from #%s" % (
                        recordedAtom.s_name, recordedAtom.i_id, str(directoryAtom.i_id)))

    def stop(self):
        self.quitEvent.set()
        logDebug("FileChangeDiscoveryThread stop requested...")
        self.join()

    @staticmethod
    def hashFileContent(s_filePath):
        h = hashlib.sha1()
        with open(s_filePath, "rb") as f:
            data = f.read(1048576)
            h.update(data)
        return h.hexdigest()

class HTTPServerThread(threading.Thread):
    def __init__(self, cfg):
        threading.Thread.__init__(self)
        self.cfg = cfg
        self.httpd = None
        self.quitEvent = threading.Event()

    def run(self):
        logDebug("HTTPServerThread starts...")
        import http.server
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                sys.stdout.flush()
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html')
                    self.end_headers()
                    self.wfile.write(bytes('Hello', 'UTF-8'))
                except Exception as e:
                    self.send_error(500, "Internal server error: " + str(e))

        t_serverAddress = ('', self.cfg.i_tcpPort)
        if not self.quitEvent.is_set():
            self.httpd = http.server.HTTPServer(t_serverAddress, Handler)
            logDebug("HTTPServerThread constructed HTTPServer object")
            try:
                self.httpd.serve_forever()
            finally:
                self.httpd.socket.close()
        while not self.quitEvent.is_set(): # .wait(timeout)
            logDebug("HTTPServerThread loops and waits for quit...")
            time.sleep(1)
        logDebug("HTTPServerThread finishes...")

    def stop(self):
        self.quitEvent.set()
        if self.httpd is not None:
            self.httpd.shutdown()
        logDebug("HTTPServerThread stop requested...")
        self.join()

def mainClient(cfg):
    pass

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--service", action="store_true",
            help="enables service mode (non-UI)")
    parser.add_argument("-c", "--client", action="store_true",
            help="enables client mode (non-UI)")
    args = parser.parse_args()

    cfg = Configuration()
    #cfg.a_locations.append(ConfigurationLocation('/tmp'))
    #cfg.a_locations.append(ConfigurationLocation('/utils'))
    cfg.a_locations.append(ConfigurationLocation('/tmp2'))

    if args.service:
        from PyQt5 import QtCore
        from PyQt5 import QtSql
        app = QtCore.QCoreApplication(sys.argv)
        discoveryThread = FileChangeDiscoveryThread(cfg)
        discoveryThread.start()
        httpdThread = HTTPServerThread(cfg)
        httpdThread.start()

        quitEvent = threading.Event()

        def sigIntHandler(signal, frame):
            logDebug("Termination requested")
            quitEvent.set()
        signal.signal(signal.SIGINT, sigIntHandler)

        while not quitEvent.wait(1):
            pass

        httpdThread.stop()
        discoveryThread.stop()
    elif args.client:
        mainClient(cfg)
    else:
        mainUI(cfg)
