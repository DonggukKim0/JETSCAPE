/*******************************************************************************
 * Copyright (c) The JETSCAPE Collaboration, 2018
 *
 * Modular, task-based framework for simulating all aspects of heavy-ion collisions
 * 
 * For the list of contributors see AUTHORS.
 *
 * Report issues at https://github.com/JETSCAPE/JETSCAPE/issues
 *
 * or via email to bugs.jetscape@gmail.com
 *
 * Distributed under the GNU General Public License 3.0 (GPLv3 or later).
 * See COPYING for details.
 ******************************************************************************/
// -----------------------------------------
// This is a wrapper for iSpectraSampler (iSS) with the JETSCAPE framework
// -----------------------------------------

#ifndef ISPECTRASAMPLERWRAPPER_H
#define ISPECTRASAMPLERWRAPPER_H

#include <memory>
#include <string>

#include "SoftParticlization.h"
#include "iSS.h"

using namespace Jetscape;

class iSpectraSamplerWrapper : public SoftParticlization {
private:
  tinyxml2::XMLElement *iSS_xml_;

  int statusCode_;
  std::unique_ptr<iSS> iSpectraSampler_ptr_;
  std::string input_file_;
  std::string table_path_;
  std::string particle_table_path_;
  std::string working_path_template_;
  std::string current_working_path_;
  bool reuse_hydro_;
  int n_reuse_hydro_;
  int last_hydro_event_idx_;

  int GetHydroEventIndex();
  std::string ResolveWorkingPath(int hydro_event_idx);
  void InitSampler(const std::string &working_path);

  // Allows the registration of the module so that it is available to be used by the Jetscape framework.
  static RegisterJetScapeModule<iSpectraSamplerWrapper> reg;

public:
  iSpectraSamplerWrapper();
  ~iSpectraSamplerWrapper();

  void InitTask();
  void Exec();
  void Clear();
  void WriteTask(weak_ptr<JetScapeWriter> w);

  int getSurfCellVector();
  void PassHadronListToJetscape();
};

#endif // ISPECTRASAMPLERWRAPPER_H
