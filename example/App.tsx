/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { 
  Shield, 
  Terminal, 
  Search, 
  Bug, 
  Zap, 
  ChevronRight, 
  CheckCircle2, 
  Info, 
  AlertTriangle,
  Lock,
  Unlock,
  Activity,
  User,
  Server
} from 'lucide-react';

interface Task {
  id: string;
  name: string;
  description: string;
  status: 'completed' | 'pending' | 'failed';
  depend_on: string[];
  result: string;
  created_at: string;
  updated_at: string;
  on_failure: string;
  attempt_count: number;
  max_attempts: number;
}

const tasks: Task[] = [
  {
    "id": "task_5aa5f457",
    "name": "[H1] Web指纹识别与目录枚举",
    "description": "对目标进行指纹识别和目录枚举，发现Web应用技术栈、隐藏路径和敏感文件",
    "status": "completed",
    "depend_on": [],
    "result": "发现Apache Tomcat/7.0.78服务在8080端口运行。识别出多个可访问路径：/, /examples/, /docs/等。Manager应用需要认证。",
    "created_at": "2026-04-27T15:47:31.894913",
    "updated_at": "2026-04-27T15:51:19.150701",
    "on_failure": "replan",
    "attempt_count": 1,
    "max_attempts": 1
  },
  {
    "id": "task_2798d4e4",
    "name": "[H2] 漏洞扫描",
    "description": "使用自动化工具对目标进行漏洞扫描，发现已知CVE和配置缺陷",
    "status": "completed",
    "depend_on": ["[H1] Web指纹识别与目录枚举"],
    "result": "发现CVE-2017-12617漏洞 - HTTP PUT方法未被正确限制，允许上传任意JSP文件。PUT返回200状态码，DELETE方法也可用。",
    "created_at": "2026-04-27T15:47:31.895313",
    "updated_at": "2026-04-27T15:51:19.150953",
    "on_failure": "replan",
    "attempt_count": 0,
    "max_attempts": 1
  },
  {
    "id": "task_3fcd1259",
    "name": "[H3] 漏洞利用",
    "description": "针对发现的漏洞进行验证和利用，获取系统访问权限或敏感信息",
    "status": "completed",
    "depend_on": ["[H2] 漏洞扫描"],
    "result": "成功利用CVE-2017-12617上传webshell并获取root权限。确认uid=0(root)执行权限，可执行任意系统命令。",
    "created_at": "2026-04-27T15:47:31.895522",
    "updated_at": "2026-04-27T15:51:19.151104",
    "on_failure": "replan",
    "attempt_count": 0,
    "max_attempts": 1
  }
];

const TaskIcon = ({ name }: { name: string }) => {
  if (name.includes('H1')) return <Search className="w-5 h-5" />;
  if (name.includes('H2')) return <Bug className="w-5 h-5" />;
  if (name.includes('H3')) return <Zap className="w-5 h-5" />;
  return <Terminal className="w-5 h-5" />;
};

export default function App() {
  const [selectedTask, setSelectedTask] = useState<Task | null>(tasks[0]);
  const [isExploited, setIsExploited] = useState(true);

  return (
    <div className="min-h-screen bg-[#09090b] text-zinc-100 font-sans selection:bg-emerald-500/30">
      {/* Grid Pattern Background */}
      <div className="fixed inset-0 grid-bg opacity-20 pointer-events-none" />

      {/* Header */}
      <header className="relative z-10 border-b border-white/5 bg-zinc-950/50 backdrop-blur-md px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-emerald-500/10 border border-emerald-500/20 rounded-lg flex items-center justify-center text-emerald-400">
            <Shield className="w-6 h-6" />
          </div>
          <div>
            <h1 className="text-xl font-bold font-mono tracking-tight text-white uppercase">Exploit Chain Atlas</h1>
            <p className="text-xs text-zinc-500 font-mono">Target System: 10.0.4.128 • Project: OS-INT_ALPHA</p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 px-3 py-1 bg-zinc-900 border border-white/10 rounded-full">
            <Activity className="w-3 h-3 text-emerald-500 animate-pulse" />
            <span className="text-[10px] font-mono text-zinc-400">SESSION ACTIVE</span>
          </div>
          <div className="flex -space-x-2">
            {[1, 2].map((i) => (
              <div key={i} className="w-8 h-8 rounded-full bg-zinc-800 border-2 border-zinc-950 flex items-center justify-center">
                <User className="w-4 h-4 text-zinc-500" />
              </div>
            ))}
          </div>
        </div>
      </header>

      <main className="relative z-10 p-6 max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        
        {/* Left Side: The Linkage Map */}
        <div className="lg:col-span-12 xl:col-span-8">
          <div className="mb-8 flex items-center justify-between">
            <h2 className="text-sm font-mono font-bold text-zinc-400 flex items-center gap-2">
              <ChevronRight className="w-4 h-4 text-emerald-500" />
              PROPAGATION_LINKAGE_FLOW
            </h2>
            <div className="text-[10px] font-mono text-zinc-500">ROOT ACCESS ACQUIRED</div>
          </div>

          <div className="relative flex flex-col items-center gap-16 py-12">
            {tasks.map((task, index) => (
              <React.Fragment key={task.id}>
                {/* Node */}
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.2 }}
                  whileHover={{ scale: 1.02 }}
                  onClick={() => setSelectedTask(task)}
                  className={`relative cursor-pointer w-full max-w-2xl group transition-all duration-300 ${
                    selectedTask?.id === task.id ? 'z-20' : 'z-10'
                  }`}
                  id={`node-${task.id}`}
                >
                  <div className={`
                    p-6 rounded-2xl border-2 transition-all duration-500
                    ${selectedTask?.id === task.id 
                      ? 'bg-zinc-900 border-emerald-500/50 shadow-[0_0_40px_-10px_rgba(16,185,129,0.2)]' 
                      : 'bg-zinc-950 border-white/5 hover:border-zinc-700/50'}
                  `}>
                    <div className="flex items-start gap-5">
                      <div className={`
                        w-12 h-12 rounded-xl flex items-center justify-center shrink-0 transition-colors
                        ${selectedTask?.id === task.id ? 'bg-emerald-500 text-zinc-950' : 'bg-zinc-900 text-zinc-400 group-hover:text-zinc-200'}
                      `}>
                        <TaskIcon name={task.name} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-[10px] font-mono text-emerald-500/80 font-bold tracking-widest">{task.status.toUpperCase()}</span>
                          <span className="text-[10px] font-mono text-zinc-500 uppercase tracking-tighter">ID: {task.id.split('_')[1]}</span>
                        </div>
                        <h3 className="text-lg font-bold text-white mb-2 font-mono truncate">{task.name}</h3>
                        <p className="text-sm text-zinc-400 line-clamp-2 mb-4 leading-relaxed">{task.description}</p>
                        
                        <div className="flex items-center gap-4">
                          <div className="flex items-center gap-1.5 px-2 py-1 bg-zinc-900/50 border border-white/5 rounded text-[10px] font-mono text-zinc-500">
                            <Info className="w-3 h-3" />
                            {task.attempt_count === 0 ? 'AUTO_SCAN' : `ATTEMPT_${task.attempt_count}`}
                          </div>
                          {task.name.includes('H3') && (
                            <div className="flex items-center gap-1.5 px-2 py-1 bg-red-500/10 border border-red-500/20 rounded text-[10px] font-mono text-red-500 font-bold">
                              <AlertTriangle className="w-3 h-3" />
                              CRITICAL_VULN
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Status Indicator Connector Glow */}
                  {selectedTask?.id === task.id && (
                    <div className="absolute -inset-1 bg-emerald-500/10 blur-xl rounded-2xl -z-10" />
                  )}
                </motion.div>

                {/* Connector Arrow */}
                {index < tasks.length - 1 && (
                  <motion.div 
                    initial={{ scaleY: 0 }}
                    animate={{ scaleY: 1 }}
                    transition={{ delay: index * 0.2 + 0.3 }}
                    className="relative w-[2px] h-16 origin-top"
                  >
                    <div className="absolute inset-0 bg-gradient-to-b from-emerald-500 to-emerald-500/20" />
                    <div className="absolute bottom-0 left-1/2 -translate-x-1/2 w-3 h-3 border-r-2 border-b-2 border-emerald-500/50 rotate-45" />
                  </motion.div>
                )}
              </React.Fragment>
            ))}

            {/* Root Success Node */}
            <motion.div
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ delay: 0.8 }}
              className="mt-8 relative group"
            >
              <div className="absolute -inset-4 bg-emerald-500/20 blur-2xl rounded-full opacity-50 group-hover:opacity-100 transition-opacity" />
              <div className="relative flex flex-col items-center">
                <div className="w-16 h-16 rounded-full bg-emerald-500 flex items-center justify-center text-zinc-950 shadow-lg shadow-emerald-500/50">
                  <Unlock className="w-8 h-8" />
                </div>
                <div className="mt-4 text-center">
                  <span className="text-[10px] font-mono font-bold text-emerald-500 tracking-[0.2em]">ACCESS_LEVEL: 0</span>
                  <h4 className="text-xl font-bold text-white font-mono uppercase italic tracking-tighter">Root Acquired</h4>
                </div>
              </div>
            </motion.div>
          </div>
        </div>

        {/* Right Side: Detail Panel */}
        <div className="lg:col-span-12 xl:col-span-4 sticky top-6">
          <AnimatePresence mode="wait">
            {selectedTask ? (
              <motion.div
                key={selectedTask.id}
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                className="bg-zinc-900/50 border border-white/5 rounded-2xl overflow-hidden backdrop-blur-xl"
              >
                <div className="p-6 border-b border-white/5 bg-zinc-900/80">
                  <div className="flex items-center justify-between mb-4">
                    <span className="text-[10px] font-mono text-zinc-500 uppercase">Analysis Results</span>
                    <button 
                      onClick={() => setSelectedTask(null)}
                      className="text-zinc-500 hover:text-white transition-colors"
                    >
                      <Terminal className="w-4 h-4" />
                    </button>
                  </div>
                  <h3 className="text-xl font-bold text-white font-mono mb-2">{selectedTask.name}</h3>
                  <div className="flex flex-wrap gap-2">
                    <span className="px-2 py-1 rounded bg-zinc-800 text-[10px] font-mono text-zinc-400 border border-white/5 flex items-center gap-1.5">
                      <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                      VERIFIED
                    </span>
                    <span className="px-2 py-1 rounded bg-zinc-800 text-[10px] font-mono text-zinc-400 border border-white/5">
                      T: {new Date(selectedTask.updated_at).toLocaleTimeString()}
                    </span>
                  </div>
                </div>

                <div className="p-6 space-y-6">
                  {/* Result Box */}
                  <div>
                    <h4 className="text-[10px] font-mono font-bold text-zinc-500 uppercase mb-3 flex items-center gap-2">
                      <Terminal className="w-3 h-3" />
                      Payload_Output
                    </h4>
                    <div className="bg-black/50 p-4 rounded-xl border border-white/5 font-mono text-xs text-zinc-300 leading-relaxed overflow-hidden relative group">
                      <div className="absolute top-0 right-0 p-2 opacity-0 group-hover:opacity-100 transition-opacity">
                        <Terminal className="w-3 h-3 text-emerald-500/50" />
                      </div>
                      <div className="mb-2 text-emerald-500/50"># cat execution_log.txt</div>
                      {selectedTask.result}
                      {/* Interactive blinking cursor */}
                      <motion.span
                        animate={{ opacity: [1, 0] }}
                        transition={{ duration: 0.8, repeat: Infinity }}
                        className="inline-block w-2 h-4 bg-emerald-500 ml-1 translate-y-1"
                      />
                    </div>
                  </div>

                  {/* Metadata */}
                  <div className="grid grid-cols-2 gap-4">
                    <div className="p-3 rounded-xl bg-white/5 border border-white/5">
                      <div className="text-[9px] font-mono text-zinc-500 uppercase mb-1">Status</div>
                      <div className="text-xs font-bold text-emerald-400">COMPLETED_0</div>
                    </div>
                    <div className="p-3 rounded-xl bg-white/5 border border-white/5">
                      <div className="text-[9px] font-mono text-zinc-500 uppercase mb-1">Max Attempts</div>
                      <div className="text-xs font-bold text-white">{selectedTask.max_attempts}</div>
                    </div>
                  </div>

                  {/* Dependent On */}
                  <div>
                    <h4 className="text-[10px] font-mono font-bold text-zinc-500 uppercase mb-3">Pre-requisites</h4>
                    <div className="space-y-2">
                      {selectedTask.depend_on.length > 0 ? (
                        selectedTask.depend_on.map((dep, i) => (
                          <div key={i} className="flex items-center gap-3 p-2 rounded-lg bg-zinc-950/30 border border-white/5 group">
                            <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0" />
                            <span className="text-xs font-mono text-zinc-400 truncate group-hover:text-zinc-200 transition-colors">{dep}</span>
                          </div>
                        ))
                      ) : (
                        <div className="text-xs font-mono text-zinc-600 italic px-2">No prerequisites defined (Root Task)</div>
                      )}
                    </div>
                  </div>

                  {/* Call to Action */}
                  <div className="pt-4">
                    <button className="w-full py-3 bg-white text-zinc-950 font-bold rounded-xl text-sm hover:bg-emerald-500 transition-colors flex items-center justify-center gap-2 group">
                      <Server className="w-4 h-4" />
                      DOWNLOAD_EXPORT
                      <ChevronRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
                    </button>
                  </div>
                </div>
              </motion.div>
            ) : (
              <div className="h-[400px] flex flex-col items-center justify-center text-center p-8 border-2 border-dashed border-white/5 rounded-2xl bg-zinc-900/20">
                <div className="w-16 h-16 rounded-full bg-zinc-900 flex items-center justify-center mb-4 text-zinc-500">
                  <Terminal className="w-8 h-8" />
                </div>
                <h3 className="text-lg font-bold text-zinc-400 mb-2">No Task Selected</h3>
                <p className="text-sm text-zinc-600 font-mono">Select a node from the map to view detailed exploitation metrics and session logs.</p>
              </div>
            )}
          </AnimatePresence>
        </div>
      </main>

      {/* Footer / Stats bar */}
      <footer className="fixed bottom-0 left-0 right-0 z-20 bg-zinc-950/80 backdrop-blur-md border-t border-white/5 px-6 py-2 flex items-center justify-between pointer-events-none xl:pointer-events-auto">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-mono text-zinc-500">CVE_COUNT:</span>
            <span className="text-[10px] font-mono text-zinc-200">01</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-mono text-zinc-500">TIME_ELAPSED:</span>
            <span className="text-[10px] font-mono text-zinc-200">03:47.12</span>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="h-4 w-[1px] bg-white/10" />
          <div className="flex items-center gap-2">
             <div className="w-2 h-2 rounded-full bg-emerald-500" />
             <span className="text-[10px] font-mono text-zinc-400 uppercase tracking-widest">System compromise fully verified</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
