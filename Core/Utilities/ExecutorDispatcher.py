
import threading, time
from DIRAC import S_OK, S_ERROR, gLogger
from DIRAC.Core.Utilities.ReturnValues import isReturnStructure
from DIRAC.Core.Utilities.ThreadScheduler import gThreadScheduler

class ExecutorState:

  def __init__( self, log = False ):
    if log:
      self.__log = log
    else:
      self.__log = gLogger
    self.__lock = threading.Lock()
    self.__typeToId = {}
    self.__maxTasks = {}
    self.__execTasks = {}
    self.__taskInExec = {}

  def _internals( self ):
    return { 't2id' : dict( self.__typeToId ),
             'maxT' : dict( self.__maxTasks ),
             'task' : dict( self.__execTasks ),
             'tine' : dict( self.__taskInExec ), }

  def addExecutor( self, eId, eType, maxTasks = 1 ):
    self.__lock.acquire()
    try:
      self.__maxTasks[ eId ] = max( 1, maxTasks )
      if eId not in self.__execTasks:
        self.__execTasks[ eId ] = set()
      if eType not in self.__typeToId:
        self.__typeToId[ eType ] = set()
      self.__typeToId[ eType ].add( eId )
    finally:
      self.__lock.release()

  def removeExecutor( self, eId ):
    self.__lock.acquire()
    try:
      tasks = []
      for eType in self.__typeToId:
        if eId in self.__typeToId[ eType ]:
          self.__typeToId[ eType ].remove( eId )
      for taskId in self.__execTasks[ eId ]:
        self.__taskInExec.pop( taskId )
        tasks.append( taskId )
      self.__execTasks.pop( eId )
      self.__maxTasks.pop( eId )
      return tasks
    finally:
      self.__lock.release()

  def getTasksForExecutor( self, eId ):
    try:
      return set( self.__execTasks[ eId ] )
    except KeyError:
      return set()

  def full( self, eId ):
    try:
      return len( self.__execTasks[ eId ] ) >= self.__maxTasks[ eId ]
    except KeyError:
      return True

  def freeSlots( self, eId ):
    try:
      return self.__maxTasks[ eId ] - len( self.__execTasks[ eId ] )
    except KeyError:
      return 0

  def getFreeExecutors( self, eType ):
    execs = {}
    try:
      eids = self.__typeToId[ eType ]
    except KeyError:
      return execs
    try:
      for eid in eids:
        freeSlots = self.freeSlots( eid )
        if freeSlots:
          execs[ eid ] = freeSlots
    except RuntimeError:
      pass
    return execs

  def getIdleExecutor( self, eType ):
    idleId = None
    maxFreeSlots = 0
    try:
      for eId in self.__typeToId[ eType ]:
        freeSlots = self.freeSlots( eId )
        if freeSlots > maxFreeSlots:
          maxFreeSlots = freeSlots
          idleId = eId
    except KeyError:
      pass
    return idleId

  def addTask( self, eId, taskId ):
    self.__lock.acquire()
    try:
      try:
        self.__taskInExec[ taskId ] = eId
        self.__execTasks[ eId ].add( taskId )
        return len( self.__execTasks[ eId ] )
      except KeyError:
        return 0
    finally:
      self.__lock.release()

  def getExecutorOfTask( self, taskId ):
    try:
      return self.__taskInExec[ taskId ]
    except KeyError:
      return None

  def removeTask( self, taskId, eId = None ):
    self.__lock.acquire()
    try:
      try:
        if eId == None:
          eId = self.__taskInExec[ taskId ]
        self.__execTasks[ eId ].remove( taskId )
        self.__taskInExec.pop( taskId )
        return True
      except KeyError:
        return False
    finally:
      self.__lock.release()

  def getTasksForExecutor( self, eId ):
    try:
      return list( self.__execTasks[ eId ] )
    except KeyError:
      return []


class ExecutorQueues:

  def __init__( self, log = False ):
    if log:
      self.__log = log
    else:
      self.__log = gLogger
    self.__lock = threading.Lock()
    self.__queues = {}
    self.__lastUse = {}
    self.__taskInQueue = {}

  def _internals( self ):
    return { 'queues' : dict( self.__queues ),
             'lastUse' : dict( self.__lastUse ),
             'taskInQueue' : dict( self.__taskInQueue ) }

  def getExecutorList( self ):
    return [ eType for eType in self.__queues ]

  def pushTask( self, eType, taskId, ahead = False ):
    self.__log.info( "Pushing task %s into waiting queue for executor %s" % ( taskId, eType ) )
    self.__lock.acquire()
    try:
      if taskId in self.__taskInQueue:
        if self.__taskInQueue[ taskId ] != eType:
          errMsg = "Task %s cannot be queued because it's already queued for %s" % ( taskId,
                                                                                    self.__taskInQueue[ taskId ] )
          self.__log.fatal( errMsg )
          return 0
        else:
          return len( self.__queues[ eType ] )
      if eType not in self.__queues:
        self.__queues[ eType ] = []
      self.__lastUse[ eType ] = time.time()
      if ahead:
        self.__queues[ eType ].insert( 0, taskId )
      else:
        self.__queues[ eType ].append( taskId )
      self.__taskInQueue[ taskId ] = eType
      return len( self.__queues[ eType ] )
    finally:
      self.__lock.release()

  def popTask( self, eType ):
    self.__lock.acquire()
    try:
      try:
        taskId = self.__queues[ eType ].pop( 0 )
        del( self.__taskInQueue[ taskId ] )
        self.__lastUse[ eType ] = time.time()
      except IndexError:
        return None
      except KeyError:
        return None
    finally:
      self.__lock.release()
    self.__log.info( "Popped task %s from executor %s waiting queue" % ( taskId, eType ) )
    return taskId

  def getState( self ):
    self.__lock.acquire()
    try:
      qInfo = {}
      for qName in self.__queues:
        qInfo[ qName ] = list( self.__queues[ qName ] )
    finally:
      self.__lock.release()
    return qInfo

  def deleteTask( self, taskId ):
    self.__log.verbose( "Deleting task %s from waiting queues" % taskId )
    self.__lock.acquire()
    try:
      try:
        eType = self.__taskInQueue[ taskId ]
        del( self.__taskInQueue[ taskId ] )
        self.__lastUse[ eType ] = time.time()
      except KeyError:
        return False
      try:
        iPos = self.__queues[ eType ].index( taskId )
      except ValueError:
        return False
      del( self.__queues[ eType ][ iPos ] )
      return True
    finally:
      self.__lock.release()

  def waitingTasks( self, eType ):
    self.__lock.acquire()
    try:
      try:
        return len( self.__queues[ eType ] )
      except KeyError:
        return 0
    finally:
      self.__lock.release()

class ExecutorDispatcherCallbacks:

  def cbDispatch( self, taskId, taskObj, pathExecuted ):
    return S_ERROR( "No dispatch callback defined" )

  def cbSendTask( self, eId, taskId, taskObj ):
    return S_ERROR( "No send task callback defined" )

  def cbDisconectExecutor( self, eId ):
    return S_ERROR( "No disconnect callback defined" )

  def cbTaskError( self, taskId, errorMsg ):
    return S_ERROR( "No error callback defined" )

  def cbTaskProcessed( self, taskId, taskObj, eType ):
    return S_OK()

class ExecutorDispatcher:

  class ETask:

    def __init__( self, taskId, taskObj ):
      self.taskId = taskId
      self.taskObj = taskObj
      self.pathExecuted = []
      self.frozenTime = 0
      self.frozenSince = 0
      self.frozenCount = 0
      self.frozenMsg = False
      self.eType = False
      self.sendTime = 0
      self.retries = 0

    def __repr__( self ):
      rS = "<ETask %s" % self.taskId
      if self.eType:
        rS += " eType=%s>" % self.eType
      else:
        rS += ">"
      return rS


  def __init__( self, monitor = False ):
    self.__idMap = {}
    self.__execTypes = {}
    self.__executorsLock = threading.Lock()
    self.__tasksLock = threading.Lock()
    self.__freezerLock = threading.Lock()
    self.__tasks = {}
    self.__log = gLogger.getSubLogger( "ExecMind" )
    self.__taskFreezer = []
    self.__queues = ExecutorQueues( self.__log )
    self.__states = ExecutorState( self.__log )
    self.__cbHolder = ExecutorDispatcherCallbacks()
    self.__monitor = monitor
    if self.__monitor:
      gThreadScheduler.addPeriodicTask( 200, self.__doMonitoringStuff )
    #If a task is frozen too many times, send error or forget task?
    self.__failedOnTooFrozen = True
    #If a task fails to properly dispatch, freeze or forget task?
    self.__freezeOnFailedDispatch = True
    #If a task needs to go to an executor that has not connected. Freeze or forget the task?
    self.__freezeOnUnknownExecutor = True

  def setFailedOnTooFrozen( self, value ):
    self.__failedOnTooFrozen = value

  def setFreezeOnFailedDispatch( self, value ):
    self.__freezeOnFailedDispatch = value

  def setFreezeOnUnknownExecutor( self, value ):
    self.__freezeOnUnknownExecutor = value


  def _internals( self ):
    return { 'idMap' : dict( self.__idMap ),
             'execTypes' : dict( self.__execTypes ),
             'tasks' : sorted( self.__tasks ),
             'freezer' : list( self.__taskFreezer ) }

  def setCallbacks( self, callbacksObj ):
    if not isinstance( callbacksObj, ExecutorDispatcherCallbacks ):
      return S_ERROR( "Callbacks object does not inherit from ExecutorDispatcherCallbacks" )
    self.__cbHolder = callbacksObj
    return S_OK()

  def __doMonitoringStuff( self ):
    if not self.__monitor:
      return
    eTypes = self.__execTypes.keys()
    for eType in eTypes:
      try:
        self.__monitor.addMark( "executors-%s" % eType, self.__execTypes[ eType ] )
      except KeyError:
        pass

  def addExecutor( self, eType, eId, maxTasks = 1 ):
    self.__log.info( "Adding new %s executor to the pool %s" % ( eId, eType ) )
    self.__executorsLock.acquire()
    try:
      if eId in self.__idMap:
        return
      self.__idMap[ eId ] = eType
      if eType not in self.__execTypes:
        self.__execTypes[ eType ] = 0
        if self.__monitor:
          self.__monitor.registerActivity( "executors-%s" % eType, "%s executors connected" % eType,
                                           "Executors", "executors", self.__monitor.OP_MEAN, 300 )
          self.__monitor.registerActivity( "tasks-%s" % eType, "Tasks processed by %s" % eType,
                                           "Executors", "tasks", self.__monitor.OP_RATE )
          self.__monitor.registerActivity( "taskTime-%s" % eType, "Task processing time for %s" % eType,
                                           "Executors", "seconds", self.__monitor.OP_MEAN )
      self.__execTypes[ eType ] += 1
      self.__states.addExecutor( eId, eType, maxTasks )
    finally:
      self.__executorsLock.release()
    self.__fillExecutors( eType )

  def removeExecutor( self, eId ):
    self.__log.info( "Removing executor %s" % eId )
    self.__executorsLock.acquire()
    try:
      if eId not in self.__idMap:
        return
      eType = self.__idMap.pop( eId )
      self.__execTypes[ eType ] -= 1
      tasksInExec = self.__states.removeExecutor( eId )
      for taskId in tasksInExec:
        self.__queues.pushTask( eType, taskId, ahead = True )
    finally:
      self.__executorsLock.release()
    try:
      self.__cbHolder.cbDisconectExecutor( eId )
    except:
      self.__log.exception( "Exception while disconnecting agent %s" % eId )
    self.__fillExecutors( eType )

  def __freezeTask( self, taskId, errMsg, eType = False ):
    self.__log.info( "Freezing task %s" % taskId )
    self.__freezerLock.acquire()
    try:
      if taskId in self.__taskFreezer:
        return False
      try:
        eTask = self.__tasks[ taskId ]
      except KeyError:
        return False
      eTask.frozenMessage = errMsg
      eTask.frozenSince = time.time()
      eTask.frozenCount += 1
      eTask.eType = eType
      isFrozen = False
      if eTask.frozenCount < 10:
        self.__taskFreezer.append( taskId )
        isFrozen = True
    finally:
      self.__freezerLock.release()
    if not isFrozen:
      self.removeTask( taskId )
      if self.__failedOnTooFrozen:
        self.__cbHolder.cbTaskError( taskId, "Retried more than 10 times. Last error: %s" % errMsg )
      return False
    return True

  def __unfreezeTasks( self, eType = False ):
    iP = 0
    while iP < len( self.__taskFreezer ):
      dispatch = False
      self.__freezerLock.acquire()
      try:
        try:
          taskId = self.__taskFreezer[ iP ]
        except IndexError:
          return
        try:
          eTask = self.__tasks[ taskId ]
        except KeyError:
          self.__log.notice( "Removing task %s from the freezer. Somebody has removed the task" % taskId )
          self.self.__taskFreezer.pop( iP )
          continue
        #Current taskId/eTask is the one to defrost
        if eType and eType == eTask.eType:
          dispatch = taskId
        elif time.time() - eTask.frozenSince > 300:
          dispatch = taskId
        if not dispatch:
          iP += 1
        else:
          self.__taskFreezer.pop( iP )
      finally:
        self.__freezerLock.release()
      #Out of the lock zone to minimize zone of exclusion
      if dispatch:
        eTask.frozenTime += time.time() - eTask.frozenSince
        self.__log.info( "Unfreezed task %s" % taskId )
        self.__dispatchTask( taskId, defrozeIfNeeded = False )

  def __addTaskIfNew( self, taskId, taskObj ):
    self.__tasksLock.acquire()
    try:
      if taskId in self.__tasks:
        self.__log.verbose( "Task %s was already known" % taskId )
        return False
      self.__tasks[ taskId ] = ExecutorDispatcher.ETask( taskId, taskObj )
      self.__log.verbose( "Added task %s" % taskId )
      return True
    finally:
      self.__tasksLock.release()

  def __dispatchTask( self, taskId, defrozeIfNeeded = True ):
    self.__log.verbose( "Dispatching task %s" % taskId )
    result = self.__getNextExecutor( taskId )

    if not result[ 'OK' ]:
      self.__log.warn( "Error while calling dispatch callback: %s" % result[ 'Message' ] )
      if self.__freezeOnFailedDispatch:
        if self.__freezeTask( taskId, result[ 'Message' ] ):
          return S_OK()
        return result
      self.removeTask( taskId )
      self.__cbHolder.cbTaskError( taskId, "Could not dispatch task: %s" % result[ 'Message' ] )
      return S_ERROR( "Could not add task. Dispatching task failed" )

    eType = result[ 'Value' ]
    if not eType:
      self.__log.info( "No more executors for task %s" % taskId )
      return self.removeTask( taskId )

    self.__log.info( "Next executor type is %s for task %s" % ( eType, taskId ) )
    if eType not in self.__execTypes:
      if  self.__freezeOnUnknownExecutor:
        self.__log.info( "Executor type %s has not connected. Freezing task %s" % ( eType, taskId ) )
        return self.__freezeTask( taskId, "Unknown executor %s type" % eType, eType = eType )
      self.__log.info( "Executor type %s has not connected. Forgetting task %s" % ( eType, taskId ) )
      return self.removeTask( taskId )

    self.__queues.pushTask( eType, taskId )
    self.__fillExecutors( eType, defrozeIfNeeded = defrozeIfNeeded )
    return S_OK()

  def __taskProcessedCallback( self, taskId, taskObj, eType ):
    try:
      result = self.__cbHolder.cbTaskProcessed( taskId, taskObj, eType )
    except:
      self.__log.exception( "Exception while calling taskDone callback" )
      return S_ERROR( "Exception while calling taskDone callback" )

    if not isReturnStructure( result ):
      errMsg = "taskDone callback did not return a S_OK/S_ERROR structure"
      self.__log.fatal( errMsg )
      return S_ERROR( errMsg )

    return result

  def __getNextExecutor( self, taskId ):
    try:
      eTask = self.__tasks[ taskId ]
    except IndexError:
      msg = "Task %s was deleted prematurely while being dispatched" % taskId
      self.__log.error( msg )
      return S_ERROR( msg )
    try:
      result = self.__cbHolder.cbDispatch( taskId, eTask.taskObj, tuple( eTask.pathExecuted ) )
    except:
      self.__log.exception( "Exception while calling dispatch callback" )
      return S_ERROR( "Exception while calling dispatch callback" )

    if not isReturnStructure( result ):
      errMsg = "Dispatch callback did not return a S_OK/S_ERROR structure"
      self.__log.fatal( errMsg )
      return S_ERROR( errMsg )

    return result

  def getTaskIds( self ):
    return self.__tasks.keys()

  def getExecutorsConnected( self ):
    return dict( self.__execTypes )

  def addTask( self, taskId, taskObj ):
    if not self.__addTaskIfNew( taskId, taskObj ):
      self.__unfreezeTasks()
      return S_OK()
    return self.__dispatchTask( taskId )

  def removeTask( self, taskId ):
    try:
      self.__tasks.pop( taskId )
    except KeyError:
      self.__log.info( "Task %s is already removed" % taskId )
      return S_OK()
    self.__log.info( "Removing task %s" % taskId )
    eId = self.__states.getExecutorOfTask( taskId )
    self.__queues.popTask( taskId )
    self.__states.removeTask( taskId )
    self.__freezerLock.acquire()
    try:
      try:
        self.__taskFreezer.pop( self.__taskFreezer.index( taskId ) )
      except KeyError:
        pass
      except ValueError:
        pass
    finally:
      self.__freezerLock.release()
    if eId:
      #Send task to executor if idle
      return self.__sendTaskToExecutor( eId, checkIdle = True )
    return S_OK()

  def taskProcessed( self, eId, taskId, taskObj = False ):
    if taskId not in self.__tasks:
      errMsg = "Task %s is not known" % taskId
      self.__log.error( errMsg )
      return S_ERROR( errMsg )
    if not self.__states.removeTask( taskId, eId ):
      errMsg = "Executor %s says it's processed task but it was not sent to it" % eId
      self.__log.error( errMsg )
      return S_ERROR( errMsg )
    try:
      eType = self.__idMap[ eId ]
    except KeyError:
      errMsg = "Executor type unknown for %s. Redoing task %s" % ( eId, taskId )
      gLogger.error( errMsg )
      self.__dispatchTask( taskId )
      return S_ERROR( errMsg )
    if self.__monitor:
      self.__monitor.addMark( "taskTime-%s" % eType, time.time() - self.__tasks[ taskId ].sendTime )
      self.__monitor.addMark( "tasks-%s" % eType, 1 )
    #Call the done callback
    result = self.__taskProcessedCallback( taskId, taskObj, eType )
    if not result[ 'OK' ]:
      return result
    #Up until here it's an executor error. From now on it can be a task error
    try:
      if taskObj:
        self.__tasks[ taskId ].taskObj = taskObj
      self.__tasks[ taskId ].pathExecuted.append( eType )
    except KeyError:
      gLogger.error( "Task %s seems to have been removed while being processed!" % taskId )
      self.__sendTaskToExecutor( eId, eType )
      return S_OK()
    self.__log.info( "Executor %s processed task %s" % ( eId, taskId ) )
    result = self.__dispatchTask( taskId )
    self.__sendTaskToExecutor( eId, eType )
    return result

  def retryTask( self, eId, taskId ):
    if taskId not in self.__tasks:
      errMsg = "Task %s is not known" % taskId
      self.__log.error( errMsg )
      return S_ERROR( errMsg )
    if not self.__states.removeTask( taskId, eId ):
      errMsg = "Executor %s says it's processed task but it was not sent to it" % eId
      self.__log.error( errMsg )
      return S_ERROR( errMsg )
    self.__log.info( "Executor %s did NOT process task %s, retrying" % ( eId, taskId ) )
    try:
      self.__tasks[ taskId ].retries += 1
    except KeyError:
      gLogger.error( "Task %s seems to have been removed while waiting for retry!" % taskId )
      return S_OK()
    return self.__dispatchTask( taskId )

  def __fillExecutors( self, eType, defrozeIfNeeded = True ):
    if defrozeIfNeeded:
      self.__log.verbose( "Unfreezing tasks for %s" % eType )
      self.__unfreezeTasks( eType )
    self.__log.verbose( "Filling %s executors" % eType )
    eId = self.__states.getIdleExecutor( eType )
    processedTasks = set()
    while eId:
      result = self.__sendTaskToExecutor( eId, eType )
      if not result[ 'OK' ]:
        self.log.error( "Could not send task to executor: %s" % result[ 'Message' ] )
      else:
        if not result[ 'Value' ]:
          #No more tasks for eType
          break
        self.__log.info( "Task %s was sent to %s" % ( result[ 'Value'], eId ) )
      eId = self.__states.getIdleExecutor( eType )
    self.__log.verbose( "No more idle executors for %s" % eType )

  def __sendTaskToExecutor( self, eId, eType = False, checkIdle = False ):
    if checkIdle and self.__states.freeSlots( eId ) == 0:
      return S_OK()
    if not eType:
      try:
        eType = self.__idMap[ eId ]
      except KeyError:
        return S_ERROR( "Executor type unknown for %s" % eId )
    taskId = self.__queues.popTask( eType )
    if taskId == None:
      self.__log.verbose( "No more tasks for %s" % eType )
      return S_OK()
    self.__log.info( "Sending task %s to %s=%s" % ( taskId, eType, eId ) )
    self.__states.addTask( eId, taskId )
    result = self.__msgTaskToExecutor( eId, taskId )
    if not result[ 'OK' ]:
      self.__queues.pushTask( eType, taskId, ahead = True )
      self.__states.removeTask( taskId )
      return result
    return S_OK( taskId )

  def __msgTaskToExecutor( self, eId, taskId ):
    try:
      result = self.__cbHolder.cbSendTask( eId, taskId, self.__tasks[ taskId ].taskObj )
    except:
      self.__log.exception( "Exception while sending task to executor" )
      return S_ERROR( "Exception while sending task to executor" )
    self.__tasks[ taskId ].sendTime = time.time()
    if isReturnStructure( result ):
      return result
    else:
      errMsg = "Send task callback did not send back an S_OK/S_ERROR structure"
      self.__log.fatal( errMsg )
      return S_ERROR( "Send task callback did not send back an S_OK/S_ERROR structure" )
    #Seems an executor problem
    self.__log.info( "Disconnecting executor" )
    self.removeExecutor( eId )
    return S_ERROR( "Exception while sending task to executor" )



if __name__ == "__main__":
  def testExecState():
    execState = ExecutorState()
    execState.addExecutor( 1, "type1", 2 )
    print execState.freeSlots( 1 ) == 2
    print execState.addTask( 1, "t1" ) == 1
    print execState.addTask( 1, "t1" ) == 1
    print execState.addTask( 1, "t2" ) == 2
    print execState.freeSlots( 1 ) == 0
    print execState.full( 1 ) == True
    print execState.removeTask( "t1" ) == 1
    print execState.freeSlots( 1 ) == 1
    print execState.getFreeExecutors( "type1" ) == {1:1}
    print execState.getTasksForExecutor( 1 ) == [ "t2" ]
    print execState.removeExecutor( 1 )
    print execState._internals()

  def testExecQueues():
    eQ = ExecutorQueues()
    for y in range( 2 ):
      for i in range( 3 ):
        print eQ.pushTask( "type%s" % y, "t%s%s" % ( y, i ) ) == i + 1
    print "DONE IN"
    print eQ.pushTask( "type0", "t01" ) == 3
    print eQ.getState()
    print eQ.popTask( "type0" ) == "t00"
    print eQ.pushTask( "type0", "t00", ahead = True ) == 3
    print eQ.popTask( "type0" ) == "t00"
    print eQ.deleteTask( "t01" ) == True
    print eQ.getState()
    print eQ.deleteTask( "t02" )
    print eQ.getState()
    for i in range( 3 ):
        print eQ.popTask( "type1" ) == "t1%s" % i
    print eQ._internals()

  testExecQueues()

