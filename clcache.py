#!/usr/bin/env python

import os
import subprocess
import sys

def findCompilerBinary():
    try:
        path = os.environ["CLCACHE_CL"]
        if os.path.exists(path):
            return path
    except KeyError:
        for dir in os.environ["PATH"].split(os.pathsep):
            path = os.path.join(dir, "cl.exe")
            if os.path.exists(path):
                return path
    return None

class CommandLine:
    def __init__(self, args):
        self.cmdline = args

    def appropriateForCaching(self):
        foundCompileOnlySwitch = False
        foundSourceFile = False
        for arg in self.cmdline[1:]:
            if arg == "/link":
                return False
            if arg == "/c":
                foundCompileOnlySwitch = True
            if arg[0] != '/':
                if foundSourceFile == True:
                    return False
                foundSourceFile = True
        return foundSourceFile and foundCompileOnlySwitch

    def outputFileName(self):
        srcFile = ""
        for arg in self.cmdline:
            if arg[:3] == "/Fo":
                return arg[3:]
            if arg[0] != '/':
                srcFile = os.path.basename(arg)
        return os.path.join(os.getcwd(), os.path.splitext(srcFile)[0] + ".obj")

class ObjectCache:
    def __init__(self):
        try:
            self.dir = os.environ["CLCACHE_DIR"]
        except KeyError:
            self.dir = os.path.join(os.path.expanduser("~"), "clcache")
        if not os.path.exists(self.dir):
            os.mkdir(self.dir)

    def cacheDirectory(self):
        return self.dir

    def clean(self, stats, maximumSize):
        currentSize = stats.currentCacheSize()
        if currentSize < maximumSize:
            return

        objects = [os.path.join(root, "object")
                   for root, folder, files in os.walk(self.dir)
                   if "object" in files]

        objectInfos = [(os.path.getatime(fn), fn) for fn in objects]

        objectsByATime = sorted(objectInfos, key=lambda t: t[0], reverse=True)

        import shutil
        for atime, fn in objectsByATime:
            objectSize = os.path.getsize(fn)
            cacheDir, fileName = os.path.split( fn )
            shutil.rmtree(cacheDir)
            currentSize -= objectSize
            if currentSize < maximumSize:
                break

        stats.setCacheSize(currentSize)

    def computeKey(self, commandLine):
        compilerBinary = commandLine[0]

        ppcmd = list(commandLine)
        ppcmd.remove("/c")
        ppcmd.append("/EP")
        preprocessedSourceCode = subprocess.Popen(ppcmd,
                                                  stdout=subprocess.PIPE,
                                                  stderr=open(os.devnull, 'w')).communicate()[0]
        normalizedCmdLine = self.__normalizedCommandLine(commandLine[1:])

        import hashlib
        sha = hashlib.sha1()
        sha.update(str(long(os.path.getmtime(compilerBinary))))
        sha.update(str(os.path.getsize(compilerBinary)))
        sha.update(' '.join(normalizedCmdLine))
        sha.update(preprocessedSourceCode)
        return sha.hexdigest()

    def hasEntry(self, key):
        return os.path.exists(self.cachedObjectName(key))

    def setEntry(self, key, objectFileName, compilerOutput):
        if not os.path.exists(self.__cacheEntryDir(key)):
            os.makedirs(self.__cacheEntryDir(key))
        import shutil
        shutil.copyfile(objectFileName, self.cachedObjectName(key))
        open(self.__cachedCompilerOutputName(key), 'w').write(compilerOutput)

    def cachedObjectName(self, key):
        return os.path.join(self.__cacheEntryDir(key), "object")

    def cachedCompilerOutput(self, key):
        return open(self.__cachedCompilerOutputName(key), 'r').read()

    def __cacheEntryDir(self, key):
        return os.path.join(self.dir, key[:2], key)

    def __cachedCompilerOutputName(self, key):
        return os.path.join(self.__cacheEntryDir(key), "output.txt")

    def __normalizedCommandLine(self, cmdline):
        def isRelevantArgument(arg):
            for preprocessorArg in [ "/AI", "/C", "/E", "/P", "/FI", "/u", "/X",
                                     "/FU", "/D", "/EP", "/Fx", "/U", "/I" ]:
                if arg[:len(preprocessorArg)] == preprocessorArg:
                    return False
            return True
        return filter(isRelevantArgument, cmdline)

class Configuration:
    def __init__(self, objectCache):
        self.configFile = os.path.join(objectCache.cacheDirectory(), "config.txt")
        self.__readConfiguration()
        self.configDirty = False

    def __del__(self):
        if self.configDirty:
            self.__writeConfiguration()

    def maximumCacheSize(self):
        return self.maximumSize

    def setMaximumCacheSize(self, size):
        self.maximumSize = size
        self.configDirty = True

    def __readConfiguration(self):
        try:
            self.maximumSize = int(open(self.configFile, 'r').read().strip())
        except:
            self.maximumSize = 1024 * 1024 * 1000

    def __writeConfiguration(self):
        open(self.configFile, 'w').write(str(self.maximumSize))

class CacheStatistics:
    def __init__(self, objectCache):
        self.cacheFile = os.path.join(objectCache.cacheDirectory(), "stats.txt")
        self.stats = self.__readStatistics()
        self.statsDirty = False

    def __del__(self):
        if self.statsDirty:
            self.__writeStatistics()

    def numInappropriateInvocations(self):
        return self.stats[0]

    def registerInappropriateInvocation(self):
        self.stats[0] += 1
        self.statsDirty = True

    def numCacheEntries(self):
        return self.stats[1]

    def registerCacheEntry(self, size):
        self.stats[1] += 1
        self.stats[4] += size
        self.statsDirty = True

    def currentCacheSize(self):
        return self.stats[4]

    def setCacheSize(self, size):
        self.stats[4] = size
        self.statsDirty = True

    def numCacheHits(self):
        return self.stats[2]

    def registerCacheHit(self):
        self.stats[2] += 1
        self.statsDirty = True

    def numCacheMisses(self):
        return self.stats[3]

    def registerCacheMiss(self):
        self.stats[3] += 1
        self.statsDirty = True

    def __readStatistics(self):
        try:
            valueStrings = open(self.cacheFile, 'r').read().strip().split(',')
            self.stats = [int(x) for x in valueStrings]
        except:
            self.stats = []

        while len(self.stats) < 5:
            self.stats.append(0)

        return self.stats

    def __writeStatistics(self):
        valueString = ','.join([str(x) for x in self.stats])
        open(self.cacheFile, 'w').write(valueString)

def printTraceStatement(msg):
    if "CLCACHE_LOG" in os.environ:
        print "*** clcache.py: " + msg

if len(sys.argv) == 2 and sys.argv[1] == "-s":
    cache = ObjectCache()
    stats = CacheStatistics(cache)
    cfg = Configuration(cache)
    print "clcache statistics:"
    print "  current cache dir  : " + cache.cacheDirectory()
    print "  cache size         : " + str(stats.currentCacheSize()) + " bytes"
    print "  maximum cache size : " + str(cfg.maximumCacheSize()) + " bytes"
    print "  cache entries      : " + str(stats.numCacheEntries())
    print "  cache hits         : " + str(stats.numCacheHits())
    print "  cache misses       : " + str(stats.numCacheMisses())
    print "  inappr. invocations: " + str(stats.numInappropriateInvocations())
    sys.exit(0)

if len(sys.argv) == 3 and sys.argv[1] == "-M":
    cache = ObjectCache()
    cfg = Configuration(cache)
    cfg.setMaximumCacheSize(int(sys.argv[2]))
    sys.exit(0)

compiler = findCompilerBinary()
cmdline = CommandLine(sys.argv)
realCmdline = [compiler] + sys.argv[1:]

if "CLCACHE_DISABLE" in os.environ:
    sys.exit(subprocess.call(realCmdline))

cache = ObjectCache()
stats = CacheStatistics(cache)
if not cmdline.appropriateForCaching():
    stats.registerInappropriateInvocation()
    printTraceStatement("Command line " + ' '.join(realCmdline) + " is not appropriate for caching, forwarding to real compiler.")
    sys.exit(subprocess.call(realCmdline))

outputFileName = cmdline.outputFileName()
cachekey = cache.computeKey(realCmdline)
if cache.hasEntry(cachekey):
    stats.registerCacheHit()
    printTraceStatement("Reusing cached object for key " + cachekey + " for output file " + cmdline.outputFileName())
    import shutil
    shutil.copyfile(cache.cachedObjectName(cachekey),
                    outputFileName)
    sys.stdout.write(cache.cachedCompilerOutput(cachekey))
    sys.exit(0)
else:
    stats.registerCacheMiss()

printTraceStatement("Invoking real compiler as " + ' '.join(realCmdline))
compilerProcess = subprocess.Popen(realCmdline, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
compilerOutput = compilerProcess.communicate()[0]

returnCode = compilerProcess.returncode
printTraceStatement("Real compiler finished with exit code " + str(returnCode) + ", object should be in " + outputFileName)

if returnCode == 0:
    printTraceStatement("Adding file " + outputFileName + " to cache using key " + cachekey)
    cache.setEntry(cachekey, outputFileName, compilerOutput)
    stats.registerCacheEntry(os.path.getsize(outputFileName))

    cfg = Configuration(cache)
    cache.clean(stats, cfg.maximumCacheSize())

sys.stdout.write(compilerOutput)
sys.exit(returnCode)


