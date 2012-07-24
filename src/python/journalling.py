#!/usr/bin/env python

# Authors:  Petr Muller     <pmuller@redhat.com>
#           Petr Splichal   <psplicha@redhat.com>
#           Ales Zelinka    <azelinka@redhat.com>
#
# Description: Provides journalling capabilities for BeakerLib
#
# Copyright (c) 2008 Red Hat, Inc. All rights reserved. This copyrighted
# material is made available to anyone wishing to use, modify, copy, or
# redistribute it subject to the terms and conditions of the GNU General
# Public License v.2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License
# for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.

from xml.dom.minidom import getDOMImplementation
import xml.dom.minidom
from optparse import OptionParser
import sys
import os
import time
import re
import rpm
import socket
import types

timeFormat="%Y-%m-%d %H:%M:%S %Z"
xmlForbidden = (0,1,2,3,4,5,6,7,8,11,12,14,15,16,17,18,19,20,\
                21,22,23,24,25,26,27,28,29,30,31,0xFFFE,0xFFFF)
xmlTrans = dict([(x,None) for x in xmlForbidden])
termColors = {
  "PASS": "\033[0;32m",
  "FAIL": "\033[0;31m",
  "INFO": "\033[0;34m",
  "WARNING": "\033[0;33m" }


def wrap(text, width):    
    return reduce(lambda line, word, width=width: '%s%s%s' %
                  (line,
                   ' \n'[(len(line)-line.rfind('\n')-1
                         + len(word.split('\n',1)[0]
                              ) >= width)],
                   word),
                  text.split(' ')
                 )

#for output redirected to file, we must not rely on python's
#automagic encoding detection - enforcing utf8 on unicode
def _print(message):
  if isinstance(message,types.UnicodeType):
    print message.encode('utf-8','replace')
  else:
    print message

def printPurpose(message):
  printHeadLog("Test description")
  _print(wrap(message, 80))

def printLog(message, prefix="LOG"):
  color = uncolor = ""
  if sys.stdout.isatty() and prefix in ("PASS", "FAIL", "INFO", "WARNING"):
    color = termColors[prefix]
    uncolor = "\033[0m"
  for line in message.split("\n"):
    _print(":: [%s%s%s] :: %s" % (color, prefix.center(10), uncolor, line))

def printHeadLog(message):
  print "\n::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::"
  printLog(message)
  print "::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::\n"

def getAllowedSeverities(treshhold):
  severities ={"DEBUG":0, "INFO":1, "WARNING":2, "ERROR":3, "FATAL":4, "LOG":5}
  allowed_severities = []
  for i in severities:
	  if (severities[i] >= severities[treshhold]): allowed_severities.append(i)
  return allowed_severities

def printPhaseLog(phase,severity):
  phaseName = phase.getAttribute("name")
  phaseResult = phase.getAttribute("result")
  starttime = phase.getAttribute("starttime")
  endtime = phase.getAttribute("endtime")
  if endtime == "":
     endtime = time.strftime(timeFormat)
  try:
    duration = time.mktime(time.strptime(endtime,timeFormat)) - time.mktime(time.strptime(starttime,timeFormat))
  except ValueError:
    # I know about two occurences:
    #   - timezones / time messed with in the test
    #   - python cannot handle the format (probably a python bug)
    duration = None 
  printHeadLog(phaseName)
  passed = 0
  failed = 0
  for node in phase.childNodes:
    if node.nodeName == "message":
      if node.getAttribute("severity") in getAllowedSeverities(severity):
        text = __childNodeValue(node, 0)
        printLog(text, node.getAttribute("severity"))
    elif node.nodeName == "test":
      result = __childNodeValue(node, 0)
      if result == "FAIL":
        printLog("%s" % node.getAttribute("message"), "FAIL")
        failed += 1
      else:
        printLog("%s" % node.getAttribute("message"), "PASS")
        passed += 1
  if duration is not None:
    formatedDuration = ''
    if (duration // 3600 > 0):
        formatedDuration = "%ih " % (duration // 3600)
        duration = duration % 3600
    if (duration // 60 > 0):
        formatedDuration += "%im " % (duration // 60)
        duration = duration % 60
    formatedDuration += "%is" % duration
  else:
    formatedDuration = "duration unknown (error when computing)"
  printLog("Duration: %s" % formatedDuration)
  printLog("Assertions: %s good, %s bad" % (passed, failed))

  printLog("RESULT: %s" % phaseName, phaseResult)
  return failed

def __childNodeValue(node, id=0):
  """Safe variant for node.childNodes[id].nodeValue()"""
  if node.hasChildNodes:
    try:
      return node.childNodes[id].nodeValue
    except IndexError:
      return ''
  else:
    return ''

def __get_hw_cpu():
  """Helper to read /proc/cpuinfo and grep count and type of CPUs from there"""
  count = 0
  type = 'unknown'
  try:
    fd = open('/proc/cpuinfo')
    expr = re.compile('^model name[\t ]+: +(.+)$')
    for line in fd.readlines():
      match = expr.search(line)
      if match != None:
        count += 1
        type = match.groups()[0]
    fd.close()
  except:
    pass
  return "%s x %s" % (count, type)

def __get_hw_ram():
  """Helper to read /proc/meminfo and grep size of RAM from there"""
  size = 'unknown'
  try:
    fd = open('/proc/meminfo')
    expr = re.compile('^MemTotal: +([0-9]+) +kB$')
    for line in fd.readlines():
      match = expr.search(line)
      if match != None:
        size = int(match.groups()[0])/1024
        break
    fd.close()
  except:
    pass
  return "%s MB" % size

def __get_hw_hdd():
  """Helper to parse size of disks from `df` output"""
  size = 0.0
  try:
    import subprocess
    output = subprocess.Popen(['df', '-k', '-P', '--local', '--exclude-type=tmpfs'], stdout=subprocess.PIPE).communicate()[0]
    output = output.split('\n')
  except ImportError:
    output = os.popen('df -k -P --local --exclude-type=tmpfs')
    output = output.readlines()
  expr = re.compile('^(/[^ ]+) +([0-9]+) +[0-9]+ +[0-9]+ +[0-9]+% +[^ ]+$')
  for line in output:
    match = expr.search(line)
    if match != None:
      size = size + float(match.groups()[1])/1024/1024
  if size == 0:
    return 'unknown'
  else:
    return "%.1f GB" % size


def createLog(id,severity,full_journal=False):
  jrnl = openJournal(id)
  printHeadLog("TEST PROTOCOL")
  phasesFailed = 0
  phasesProcessed = 0

  for node in jrnl.childNodes[0].childNodes:
    if node.nodeName == "test_id":
      printLog("Test run ID   : %s" % __childNodeValue(node, 0))
    elif node.nodeName == "package":
      printLog("Package       : %s" % __childNodeValue(node, 0))
    elif node.nodeName == "testname":
      printLog("Test name     : %s" % __childNodeValue(node, 0))
    elif node.nodeName == "pkgdetails":
      printLog("Installed:    : %s" % __childNodeValue(node, 0))
    elif node.nodeName == "release":
      printLog("Distro:       : %s" % __childNodeValue(node, 0))
    elif node.nodeName == "starttime":
      printLog("Test started  : %s" % __childNodeValue(node, 0))
    elif node.nodeName == "endtime":
      printLog("Test finished : %s" % __childNodeValue(node, 0))
    elif node.nodeName == "arch":
      printLog("Architecture  : %s" % __childNodeValue(node, 0))
    elif node.nodeName == "hw_cpu" and full_journal:
      printLog("CPUs          : %s" % __childNodeValue(node, 0))
    elif node.nodeName == "hw_ram" and full_journal:
      printLog("RAM size      : %s" % __childNodeValue(node, 0))
    elif node.nodeName == "hw_hdd" and full_journal:
      printLog("HDD size      : %s" % __childNodeValue(node, 0))
    elif node.nodeName == "hostname":
      printLog("Hostname      : %s" % __childNodeValue(node, 0))
    elif node.nodeName == "plugin":
      printLog("Plugin        : %s" % __childNodeValue(node, 0))
    elif node.nodeName == "purpose":
      printPurpose(__childNodeValue(node, 0))
    elif node.nodeName == "log":
      for nod in node.childNodes:
        if nod.nodeName == "message":
          if nod.getAttribute("severity") in getAllowedSeverities(severity):
            if (len(nod.childNodes) > 0):
              text = __childNodeValue(nod, 0)
            else:
              text = ""
            printLog(text, nod.getAttribute("severity"))
        elif nod.nodeName == "test":
          printLog("TEST BUG: Assertion not in phase", "WARNING")
          result = __childNodeValue(nod, 0)
          if result == "FAIL":
            printLog("%s" % nod.getAttribute("message"), "FAIL")
          else:
            printLog("%s" % nod.getAttribute("message"), "PASS")
        elif nod.nodeName == "metric":
          printLog("%s: %s" % (nod.getAttribute("name"), __childNodeValue(nod, 0)), "METRIC")
        elif nod.nodeName == "phase":
	  phasesProcessed += 1
	  if printPhaseLog(nod,severity) > 0:
            phasesFailed += 1

  testName = __childNodeValue(jrnl.getElementsByTagName("testname")[0],0)
  printHeadLog(testName)
  printLog("Phases: %d good, %d bad" % ((phasesProcessed - phasesFailed),phasesFailed))
  printLog("RESULT: %s" % testName, (phasesFailed == 0 and "PASS" or "FAIL"))

def initializeJournal(id, test, package):
  # if the journal already exists, do not overwrite it
  try: jrnl = _openJournal(id)
  except: pass
  else: return

  impl = getDOMImplementation()  
  newdoc = impl.createDocument(None, "BEAKER_TEST", None)
  top_element = newdoc.documentElement
  testidEl    = newdoc.createElement("test_id")
  testidCon   = newdoc.createTextNode(str(id))  
  packageEl   = newdoc.createElement("package")
  packageCon  = newdoc.createTextNode(str(package))
  pkgDetailsEl = newdoc.createElement("pkgdetails")

  pkgdetails = []
  pkgnames = [package]

  if 'PKGNVR' in os.environ:
    for p in os.environ['PKGNVR'].split(','):
      pkgnames.append(p)

  ts = rpm.ts()
  for pkgname in pkgnames:
    mi = ts.dbMatch("name", pkgname)
    for pkg in mi:
      pkgDetailsCon = newdoc.createTextNode("%(name)s-%(version)s-%(release)s.%(arch)s " % pkg)
      pkgdetails.append((pkgDetailsEl, pkgDetailsCon))

  startedEl   = newdoc.createElement("starttime")
  startedCon  = newdoc.createTextNode(time.strftime(timeFormat))

  endedEl     = newdoc.createElement("endtime")
  endedCon    = newdoc.createTextNode(time.strftime(timeFormat))

  hostnameEl     = newdoc.createElement("hostname")
  hostnameCon   = newdoc.createTextNode(socket.getfqdn())

  archEl     = newdoc.createElement("arch")
  archCon   = newdoc.createTextNode(os.uname()[-1])

  hw_cpuEl    = newdoc.createElement("hw_cpu")
  hw_cpuCon   = newdoc.createTextNode(__get_hw_cpu())

  hw_ramEl    = newdoc.createElement("hw_ram")
  hw_ramCon   = newdoc.createTextNode(__get_hw_ram())

  hw_hddEl    = newdoc.createElement("hw_hdd")
  hw_hddCon   = newdoc.createTextNode(__get_hw_hdd())

  testEl      = newdoc.createElement("testname")
  testCon     = newdoc.createTextNode(str(test))

  releaseEl   = newdoc.createElement("release")
  releaseCon  = newdoc.createTextNode(open("/etc/redhat-release",'r').read().strip())
  logEl       = newdoc.createElement("log")
  purposeEl   = newdoc.createElement("purpose")
  try:  
    purpose_file = open("PURPOSE", 'r')
    purpose = purpose_file.read()
    purpose_file.close()
  except IOError:
    purpose = "Cannot find the PURPOSE file of this test. Could be a missing, or rlInitializeJournal wasn't called from appropriate location"

  purposeCon  = newdoc.createTextNode(unicode(purpose,'utf-8').translate(xmlTrans))

  shre = re.compile(".+\.sh$")
  bpath = os.environ["BEAKERLIB"]
  plugpath = os.path.join(bpath, "plugin")
  plugins = []

  if os.path.exists(plugpath):
    for file in os.listdir(plugpath):
      if shre.match(file):
        plugEl = newdoc.createElement("plugin")
        plugCon = newdoc.createTextNode(file)
        plugins.append((plugEl, plugCon))

  testidEl.appendChild(testidCon)
  packageEl.appendChild(packageCon)
  for installed_pkg in pkgdetails:
    installed_pkg[0].appendChild(installed_pkg[1])
  startedEl.appendChild(startedCon)
  endedEl.appendChild(endedCon)
  testEl.appendChild(testCon)
  releaseEl.appendChild(releaseCon)
  purposeEl.appendChild(purposeCon)
  hostnameEl.appendChild(hostnameCon)
  archEl.appendChild(archCon)
  hw_cpuEl.appendChild(hw_cpuCon)
  hw_ramEl.appendChild(hw_ramCon)
  hw_hddEl.appendChild(hw_hddCon)
  for plug in plugins:
    plug[0].appendChild(plug[1])

  top_element.appendChild(testidEl)
  top_element.appendChild(packageEl)
  for installed_pkg in pkgdetails:
    top_element.appendChild(installed_pkg[0])
  top_element.appendChild(startedEl)
  top_element.appendChild(endedEl)
  top_element.appendChild(testEl)
  top_element.appendChild(releaseEl)
  top_element.appendChild(hostnameEl)
  top_element.appendChild(archEl)
  top_element.appendChild(hw_cpuEl)
  top_element.appendChild(hw_ramEl)
  top_element.appendChild(hw_hddEl)
  for plug in plugins:
    top_element.appendChild(plug[0])
  top_element.appendChild(purposeEl)
  top_element.appendChild(logEl)
  
  saveJournal(newdoc, id)

def saveJournal(newdoc, id):
  journal = '/tmp/beakerlib-%s/journal.xml' % id
  try:
    output = open(journal, 'wb')
    output.write(newdoc.toxml().encode('utf-8'))
    output.close()
  except IOError:
    printLog('Failed to save journal to %s' % journal, 'BEAKERLIB_WARNING')
    sys.exit(1)

def _openJournal(id):
  jrnl = xml.dom.minidom.parse("/tmp/beakerlib-%s/journal.xml" % id )
  return jrnl

def openJournal(id):
  try:
    jrnl = _openJournal(id)
  except (IOError, EOFError):
    printLog('Journal not initialised? Trying it now.', 'BEAKERLIB_WARNING')
    initializeJournal(id,
                      os.environ.get("TEST", "some test"),
                      os.environ.get("PACKAGE", "some package"))
    jrnl = _openJournal(id)
  return jrnl

def getLogEl(jrnl):
  for node in jrnl.getElementsByTagName('log'):
    return node
  
def getLastUnfinishedPhase(tree):
  candidate = tree
  for node in tree.getElementsByTagName('phase'):
    if node.getAttribute('result') == 'unfinished':
      candidate = node
  return candidate

def addPhase(id, name, type):
  jrnl = openJournal(id)  
  log = getLogEl(jrnl)  
  phase = jrnl.createElement("phase")
  phase.setAttribute("name", unicode(name,'utf-8').translate(xmlTrans))
  phase.setAttribute("result", 'unfinished')
  phase.setAttribute("type", unicode(type,'utf-8'))
  phase.setAttribute("starttime",time.strftime(timeFormat))
  phase.setAttribute("endtime","")
  log.appendChild(phase)
  saveJournal(jrnl, id)

def getPhaseState(phase):
  passed = failed = 0
  for node in phase.childNodes:
    if node.nodeName == "test":
      result = __childNodeValue(node, 0)
      if result == "FAIL":
        failed += 1
      else:
        passed += 1
  return (passed,failed)

def finPhase(id):
  jrnl  = openJournal(id)
  phase = getLastUnfinishedPhase(getLogEl(jrnl))
  type  = phase.getAttribute('type')
  name  = phase.getAttribute('name')
  end   = jrnl.getElementsByTagName('endtime')[0]
  timeNow = time.strftime(timeFormat)
  end.childNodes[0].nodeValue = timeNow
  phase.setAttribute("endtime",timeNow)
  (passed,failed)=getPhaseState(phase)
  if failed == 0:
    phase.setAttribute("result", 'PASS')
  else:
    phase.setAttribute("result", type)

  phase.setAttribute('score', str(failed))
  saveJournal(jrnl, id)
  return (phase.getAttribute('result'), phase.getAttribute('score'), type, name)

def getPhase(tree):
  for node in tree.getElementsByTagName("phase"):
    if node.getAttribute("name") == name:
      return node
  return tree

def testState(id):
  jrnl  = openJournal(id)
  failed = 0
  for phase in jrnl.getElementsByTagName('phase'):
    failed += getPhaseState(phase)[1]
  if failed >255:
      failed = 255
  return failed

def phaseState(id):
  jrnl  = openJournal(id)
  phase = getLastUnfinishedPhase(getLogEl(jrnl))
  failed=getPhaseState(phase)[1]
  if failed >255:
      failed = 255
  return failed


def addMessage(id, message, severity):
  jrnl = openJournal(id)  
  log = getLogEl(jrnl)  
  add_to = getLastUnfinishedPhase(log)    
  
  msg = jrnl.createElement("message")
  msg.setAttribute("severity", severity)  
  
  msgText = jrnl.createTextNode(unicode(message,"utf-8").translate(xmlTrans))
  msg.appendChild(msgText)
  add_to.appendChild(msg)
  saveJournal(jrnl, id)

def addTest(id, message, result="FAIL"):
  jrnl = openJournal(id)
  log = getLogEl(jrnl)
  add_to = getLastUnfinishedPhase(log)
  
  msg = jrnl.createElement("test")
  msg.setAttribute("message", unicode(message,'utf-8').translate(xmlTrans))
  
  msgText = jrnl.createTextNode(result)
  msg.appendChild(msgText)
  add_to.appendChild(msg)
  saveJournal(jrnl, id)

def addMetric(id, type, name, value, tolerance):
  jrnl = openJournal(id)
  log = getLogEl(jrnl)
  add_to = getLastUnfinishedPhase(log)

  for node in add_to.getElementsByTagName('metric'):
    if node.getAttribute('name') == name:
        raise Exception("Metric name not unique!")

  metric = jrnl.createElement("metric")
  metric.setAttribute("type", type)
  metric.setAttribute("name", name)
  metric.setAttribute("tolerance", str(tolerance))

  metricText = jrnl.createTextNode(str(value))
  metric.appendChild(metricText)
  add_to.appendChild(metric)
  saveJournal(jrnl, id)

def dumpJournal(id, type):
  if type == "raw":
    print openJournal(id).toxml().encode("utf-8")
  elif type == "pretty":    
    print openJournal(id).toprettyxml().encode("utf-8")
  else:
    print "Journal dump error: bad type specification"
  
def need(args):
  if None in args:
    print "need Blargh!"
    sys.exit(1)  

DESCRIPTION = "Wrapper for operations above BeakerLib journal"
optparser = OptionParser(description=DESCRIPTION)

optparser.add_option("-i", "--id", default=None, dest="testid", metavar="TEST-ID")
optparser.add_option("-p", "--package", default=None, dest="package", metavar="PACKAGE")
optparser.add_option("-t", "--test", default=None, dest="test", metavar="TEST")
optparser.add_option("-n", "--name", default=None, dest="name", metavar="NAME")
optparser.add_option("-s", "--severity", default=None, dest="severity", metavar="SEVERITY")
optparser.add_option("-f", "--full-journal", action="store_true", default=False, dest="full_journal", metavar="FULL_JOURNAL")
optparser.add_option("-m", "--message", default=None, dest="message", metavar="MESSAGE")
optparser.add_option("-r", "--result", default=None, dest="result")
optparser.add_option("-v", "--value", default=None, dest="value")
optparser.add_option("--tolerance", default=None, dest="tolerance")
optparser.add_option("--type", default=None, dest="type")


(options, args) = optparser.parse_args()

if len(args) != 1:
  print "Argh Blargh!: %s" % len(args)
  sys.exit(1)

command = args[0]

if command == "init":
  need((options.testid, options.test, options.package))  
  initializeJournal(options.testid, options.test, options.package) 
elif command == "dump":
  need((options.testid, options.type))
  dumpJournal(options.testid, options.type)
elif command == "printlog":
  need((options.testid,options.severity,options.full_journal))
  createLog(options.testid, options.severity, options.full_journal)
elif command == "addphase":
  need((options.testid, options.name, options.type))
  addPhase(options.testid, options.name, options.type)
  printHeadLog(options.name)
elif command == "log":
  need((options.message, options.testid))  
  severity = options.severity
  if severity is None:
    severity = "LOG"
  addMessage(options.testid, options.message, severity)
elif command == "test":
  need((options.testid, options.message))  
  result = options.result
  if result is None:
    result = "FAIL"
  addTest(options.testid, options.message, result)
  printLog(options.message, result)
elif command == "metric":
  need((options.testid, options.name, options.type, options.value, options.tolerance))
  try:
    addMetric(options.testid, options.type, options.name, float(options.value), float(options.tolerance))
  except:
    sys.exit(1)
elif command == "finphase":
  need((options.testid,))
  result, score, type, name = finPhase(options.testid)
  _print("%s:%s:%s" % (type,result,name))
  sys.exit(int(score))
elif command == "teststate":
  need((options.testid,))
  failed = testState(options.testid)
  sys.exit(failed)
elif command == "phasestate":
  need((options.testid,))
  failed = phaseState(options.testid)
  sys.exit(failed)

sys.exit(0)
