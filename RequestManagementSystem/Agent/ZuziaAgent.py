"""  Zuzia picks out the requests that she finds then tries to put them in the central server.
"""

from DIRAC  import gLogger, gConfig, gMonitor, S_OK, S_ERROR
from DIRAC.Core.Base.Agent import Agent
from DIRAC.RequestManagementSystem.Client.RequestClient import RequestClient

import time,os,re
from types import *

AGENT_NAME = 'RequestManagement/ZuziaAgent'

class ZuziaAgent(Agent):

  def __init__(self):
    """ Standard constructor
    """
    Agent.__init__(self,AGENT_NAME)

  def initialize(self):
    result = Agent.initialize(self)
    self.RequestDBClient = RequestClient()

    gMonitor.registerActivity("Iteration",          "Agent Loops",                  "ZuziaAgent",      "Loops/min",      gMonitor.OP_SUM)
    gMonitor.registerActivity("Attempted",          "Request Processed",            "ZuziaRAgent",     "Requests/min",   gMonitor.OP_SUM)
    gMonitor.registerActivity("Successful",         "Request Forward Successful",   "ZuziaAgent",      "Requests/min",   gMonitor.OP_SUM)
    gMonitor.registerActivity("Failed",             "Request Forward Failed",       "ZuziaAgent",      "Requests/min",   gMonitor.OP_SUM)

    self.local = PathFinder.getServiceURL("RequestManagement/localURL")
    if not self.local:
      errStr = 'The RequestManagement/localURL option must be defined.'
      gLogger.fatal(errStr)
      return S_ERROR(errStr)

    self.central = PathFinder.getServiceURL("RequestManagement/centralURL")
    if not self.central:
      errStr = 'The RequestManagement/centralURL option must be defined.'
      gLogger.fatal(errStr)
      return S_ERROR(errStr)
    return result

  def execute(self):
    """ This agent is the smallest and (cutest) of all the DIRAC agents in existence.
    """
    gMonitor.addMark("Iteration",1)

    res = self.RequestDBClient.serveRequest(requestType='',url=self.local)
    if not res['OK']:
      gLogger.error("ZuziaAgent.execute: Failed to get request from database.",self.local)
      return S_OK()
    elif not res['Value']:
      gLogger.info("ZuziaAgent.execute: No requests to be executed found.")
      return S_OK()

    gMonitor.addMark("Attempted",1)

    requestString = res['Value']['RequestString']
    requestName = res['Value']['RequestName']
    gLogger.info("ZuziaAgent.execute: Obtained request %s" % requestName)

    gLogger.info("ZuziaAgent.execute: Attempting to set request to %s." % self.central)
    res = self.RequestDBClient.setRequest(requestName,requestString,self.central)
    if res['OK']:
      gMonitor.addMark("Successful",1)
      gLogger.info("ZuziaAgent.execute: Successfully put request.")
    else:
      gMonitor.addMark("Failed",1)
      gLogger.error("ZuziaAgent.execute: Failed to set request to", self.central)
      gLogger.info("ZuziaAgent.execute: Attempting to set request to %s." % self.local)
      res = self.RequestDBClient.setRequest(requestName,requestString,self.local)
      if res['OK']:
        gLogger.info("ZuziaAgent.execute: Successfully put request.")
      else:
        gLogger.error("ZuziaAgent.execute: Failed to set request to", self.local)
        while not res['OK']:
          gLogger.info("ZuziaAgent.execute: Attempting to set request to anywhere.")
          res = self.RequestDBClient.setRequest(requestName,requestString)
        gLogger.info("ZuziaAgent.execute: Successfully put request to %s." % res["Server"])
    return S_OK()
